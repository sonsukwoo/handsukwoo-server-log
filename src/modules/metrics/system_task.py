import logging
import os
import time
from datetime import datetime

import psutil
import requests

from src.database.connection import SessionLocal
from .models import CpuMetric, MemoryMetric, DiskMetric, NetworkMetric

logger = logging.getLogger("SYSTEM")

# 기본적으로 .env에서 읽어오고 설정이 없으면 localhost 사용
NETDATA_HOST = os.getenv("NETDATA_HOST", "localhost")
BASE_URL = f"http://{NETDATA_HOST}:19999/api/v1/data?after=-1&points=1&format=json&chart="

_LAST_NET_IF_STATS = {}
_LAST_NET_TS = None

def get_netdata(chart):
    try:
        r = requests.get(BASE_URL + chart, timeout=5)
        data = r.json()
        if not data.get('data'): return None
        cols = data['labels']
        vals = data['data'][0]
        return {cols[i]: vals[i] for i in range(len(cols))}
    except Exception as e:
        logger.error(f"Netdata 연결 실패 ({chart}): {e}")
        return None

def collect_cpu_metrics(ts=None, batch_id=None):
    cpu = get_netdata('system.cpu')
    load = get_netdata('system.load')
    if not (cpu and load):
        return None

    db = SessionLocal()
    try:
        metric_time = ts if ts else datetime.fromtimestamp(cpu['time'])
        batch_id = batch_id or metric_time.isoformat()

        cpu_user = round(cpu.get('user', 0.0), 2)
        cpu_system = round(cpu.get('system', 0.0), 2)
        cpu_iowait = round(cpu.get('iowait', 0.0), 2)
        cpu_total = round(
            cpu_user
            + cpu_system
            + cpu_iowait
            + cpu.get('softirq', 0)
            + cpu.get('irq', 0),
            2,
        )

        cpu_cores = os.cpu_count() or 1

        new_metric = CpuMetric(
            ts=metric_time,
            batch_id=batch_id,
            core_count=cpu_cores,
            cpu_percent=cpu_total,
            cpu_user=cpu_user,
            cpu_system=cpu_system,
            cpu_iowait=cpu_iowait,
            load_1min=round(load['load1'], 2),
            load_5min=round(load['load5'], 2),
            load_15min=round(load['load15'], 2),
        )

        db.add(new_metric)
        db.commit()

        logger.info(f"CPU 지표 저장 완료 (CPU: {new_metric.cpu_percent}%)")
        return f"CPU: {new_metric.cpu_percent}%"
    except Exception as e:
        db.rollback()
        if "unique constraint" in str(e).lower():
            logger.warning("중복된 타임스탬프 데이터 스킵 (CPU)")
        else:
            logger.error(f"CPU 저장 중 오류 발생: {e}")
        return None
    finally:
        db.close()


def collect_memory_metrics(ts=None, batch_id=None):
    ram = get_netdata('system.ram')
    if not ram:
        return None

    db = SessionLocal()
    try:
        metric_time = ts if ts else datetime.fromtimestamp(ram['time'])
        batch_id = batch_id or metric_time.isoformat()

        mem_used = round(ram.get('used', 0.0), 1)
        mem_free = round(ram.get('free', 0.0), 1)
        mem_cached = round(ram.get('cached', 0.0), 1)
        mem_buffers = round(ram.get('buffers', 0.0), 1)
        mem_total = round(mem_used + mem_free + mem_cached + mem_buffers, 1)
        mem_percent = round((mem_used / mem_total) * 100.0, 2) if mem_total > 0 else 0.0

        swap = psutil.swap_memory()
        swap_total = round(swap.total / (1024 * 1024), 1)
        swap_used = round(swap.used / (1024 * 1024), 1)

        new_metric = MemoryMetric(
            ts=metric_time,
            batch_id=batch_id,
            mem_total_mb=mem_total,
            mem_used_mb=mem_used,
            mem_free_mb=mem_free,
            mem_percent=mem_percent,
            mem_cached_mb=mem_cached,
            mem_buffers_mb=mem_buffers,
            swap_total_mb=swap_total,
            swap_used_mb=swap_used,
        )

        db.add(new_metric)
        db.commit()

        logger.info(f"메모리 지표 저장 완료 (RAM: {new_metric.mem_percent}%)")
        return f"RAM: {new_metric.mem_percent}%"
    except Exception as e:
        db.rollback()
        if "unique constraint" in str(e).lower():
            logger.warning("중복된 타임스탬프 데이터 스킵 (MEM)")
        else:
            logger.error(f"메모리 저장 중 오류 발생: {e}")
        return None
    finally:
        db.close()


def collect_disk_metrics(ts=None, batch_id=None):
    metric_time = ts if ts else datetime.now()
    batch_id = batch_id or metric_time.isoformat()
    partitions = psutil.disk_partitions(all=False)

    db = SessionLocal()
    try:
        metrics_to_save = []
        for p in partitions:
            try:
                usage = psutil.disk_usage(p.mountpoint)
            except PermissionError:
                continue

            new_metric = DiskMetric(
                ts=metric_time,
                batch_id=batch_id,
                mount=p.mountpoint,
                disk_total_gb=round(usage.total / (1024 ** 3), 2),
                disk_used_gb=round(usage.used / (1024 ** 3), 2),
                disk_free_gb=round(usage.free / (1024 ** 3), 2),
                disk_percent=round(usage.percent, 2),
            )
            metrics_to_save.append(new_metric)

        if metrics_to_save:
            db.bulk_save_objects(metrics_to_save)
            db.commit()
            logger.info(f"디스크 지표 저장 완료 ({len(metrics_to_save)}개 마운트)")
            return f"Disk: {len(metrics_to_save)} mounts"
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"디스크 저장 중 오류 발생: {e}")
        return None
    finally:
        db.close()


def collect_network_metrics(ts=None, batch_id=None):
    global _LAST_NET_IF_STATS, _LAST_NET_TS

    metric_time = ts if ts else datetime.now()
    batch_id = batch_id or metric_time.isoformat()
    now_ts = time.time()
    counters = psutil.net_io_counters(pernic=True)

    db = SessionLocal()
    try:
        metrics_to_save = []
        for iface, stats in counters.items():
            prev = _LAST_NET_IF_STATS.get(iface)
            rate_rx = 0.0
            rate_tx = 0.0
            if prev and _LAST_NET_TS:
                dt = now_ts - _LAST_NET_TS
                if dt > 0:
                    rate_rx = (stats.bytes_recv - prev.bytes_recv) / dt
                    rate_tx = (stats.bytes_sent - prev.bytes_sent) / dt

            new_metric = NetworkMetric(
                ts=metric_time,
                batch_id=batch_id,
                interface=iface,
                rx_bytes=stats.bytes_recv,
                tx_bytes=stats.bytes_sent,
                rx_rate_bps=round(rate_rx, 2),
                tx_rate_bps=round(rate_tx, 2),
            )
            metrics_to_save.append(new_metric)

        if metrics_to_save:
            db.bulk_save_objects(metrics_to_save)
            db.commit()
            logger.info(f"네트워크 지표 저장 완료 ({len(metrics_to_save)}개 인터페이스)")
            return f"Network: {len(metrics_to_save)} interfaces"
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"네트워크 저장 중 오류 발생: {e}")
        return None
    finally:
        _LAST_NET_IF_STATS = counters
        _LAST_NET_TS = now_ts
        db.close()
