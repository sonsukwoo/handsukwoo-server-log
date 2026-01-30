import requests
import logging
import os
from datetime import datetime
from src.database.connection import SessionLocal
from .models import SystemMetric

logger = logging.getLogger("SYSTEM")

# 기본적으로 .env에서 읽어오고 설정이 없으면 localhost 사용
NETDATA_HOST = os.getenv("NETDATA_HOST", "localhost")
BASE_URL = f"http://{NETDATA_HOST}:19999/api/v1/data?after=-1&points=1&format=json&chart="

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

def collect_system_metrics(ts=None):
    # 1. Netdata에서 데이터 가져오기
    cpu = get_netdata('system.cpu')
    ram = get_netdata('system.ram')
    load = get_netdata('system.load')

    if not (cpu and ram and load):
        return None

    db = SessionLocal()
    try:
        # 3. 모델 객체 생성 (데이터 매핑)
        metric_time = ts if ts else datetime.fromtimestamp(cpu['time'])
        
        # CPU 상세 계산
        cpu_user = round(cpu.get('user', 0.0), 2)
        cpu_system = round(cpu.get('system', 0.0), 2)
        cpu_iowait = round(cpu.get('iowait', 0.0), 2)
        cpu_total = round(cpu_user + cpu_system + cpu_iowait + cpu.get('softirq', 0) + cpu.get('irq', 0), 2)
        
        import os
        cpu_cores = os.cpu_count() or 1 # cpu_count()가 None일 경우 대비

        # RAM 계산
        ram_used = round(ram['used'], 1)
        ram_total = round(ram['used'] + ram['free'] + ram.get('cached', 0) + ram.get('buffers', 0), 1)
        ram_percent = round((ram_used / ram_total) * 100.0, 2) if ram_total > 0 else 0.0

        new_metric = SystemMetric(
            ts=metric_time,
            cpu_user=cpu_user,
            cpu_system=cpu_system,
            cpu_iowait=cpu_iowait,
            cpu_total=cpu_total,
            cpu_cores=cpu_cores,
            
            ram_total_mb=ram_total,
            ram_used_mb=ram_used,
            ram_percent=ram_percent,
            
            load_1min=round(load['load1'], 2),
            load_5min=round(load['load5'], 2),
            load_15min=round(load['load15'], 2)
        )
        
        db.add(new_metric)
        db.commit()
        
        logger.info(f"시스템 지표 저장 완료 (CPU: {new_metric.cpu_total}%, RAM: {new_metric.ram_percent}% [{new_metric.ram_used_mb}/{new_metric.ram_total_mb}MB])")
        return f"System: {new_metric.cpu_total}% CPU, {new_metric.ram_percent}% RAM"
        
    except Exception as e:
        db.rollback()
        if "unique constraint" in str(e).lower():
            logger.warning("중복된 타임스탬프 데이터 스킵")
        else:
            logger.error(f"DB 저장 중 오류 발생: {e}")
        return None
    finally:
        db.close()
