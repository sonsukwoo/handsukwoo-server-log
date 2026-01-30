import logging
import os
from datetime import datetime

# [CRITICAL] docker 라이브러리가 로드되기 전에 환경변수를 먼저 정리합니다.
# http+docker:// 관련 에러 방지를 위해 강제로 초기화합니다.
for env_key in ['DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH']:
    if env_key in os.environ:
        del os.environ[env_key]

import docker
from src.database.connection import SessionLocal
from .models import DockerMetric

logger = logging.getLogger("DOCKER")

def calculate_cpu_percent(stats):
    """
    도커 통계 데이터를 바탕으로 CPU 사용률(%) 계산
    """
    cpu_percent = 0.0
    try:
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                    stats['precpu_stats']['cpu_usage']['total_usage']
        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                       stats['precpu_stats']['system_cpu_usage']
        
        if system_delta > 0.0 and cpu_delta > 0.0:
            # (CPU 변화량 / 시스템 CPU 변화량) * 코어 수 * 100
            # percpu_usage 길이로 코어 수를 추정
            per_cpu = stats['cpu_stats']['cpu_usage'].get('percpu_usage')
            if per_cpu is None:
                per_cpu = [1] # fallback
                
            cpu_percent = (cpu_delta / system_delta) * len(per_cpu) * 100.0
    except KeyError:
        cpu_percent = 0.0
    return cpu_percent

def collect_docker_metrics(ts=None):
    """
    실행 중인 모든 도커 컨테이너의 지표를 수집하여 DB에 저장
    ts: main.py에서 전달받은 동기화된 타임스탬프
    """
    if ts is None:
        ts = datetime.now()

    db = SessionLocal()
    try:
        client = None
        # 도커 소켓 직접 연결 (가장 확실한 방법)
        try:
            # unix:// 형식을 사용하거나, context와 상관없이 소켓 직접 지적
            client = docker.DockerClient(base_url='unix://var/run/docker.sock')
            client.ping()
        except Exception as e:
            logger.warning(f"표준 소켓 연결 실패 ({e}), 폴백(from_env) 시도...")
            try:
                client = docker.from_env()
                client.ping()
            except Exception as env_e:
                logger.error(f"도커 모든 연결수단 실패: {env_e}")
                return None

        containers = client.containers.list()
        
        metrics_to_save = []
        for container in containers:
            try:
                # stream=False로 설정하여 1회성 스냅샷 가져오기
                stats = container.stats(stream=False)
                
                cpu_p = calculate_cpu_percent(stats)
                
                # 메모리 계산
                mem_usage = stats['memory_stats'].get('usage', 0)
                mem_limit = stats['memory_stats'].get('limit', 0)
                mem_used_mb = mem_usage / (1024 * 1024)
                mem_percent = 0.0
                if mem_limit > 0:
                    mem_percent = (mem_usage / mem_limit) * 100.0
                
                new_metric = DockerMetric(
                    ts=ts,
                    container_id=container.short_id,
                    container_name=container.name,
                    cpu_percent=cpu_p,
                    mem_used_mb=mem_used_mb,
                    mem_percent=mem_percent
                )
                metrics_to_save.append(new_metric)
                
            except Exception as e:
                logger.warning(f"컨테이너 {container.name} 지표 수집 실패: {e}")
                continue

        if metrics_to_save:
            db.bulk_save_objects(metrics_to_save)
            db.commit()
            logger.info(f"도커 지표 저장 완료 ({len(metrics_to_save)}개 컨테이너)")
            return f"Docker: {len(metrics_to_save)} containers collected"
        
    except Exception as e:
        db.rollback()
        logger.error(f"도커 수집 중 오류 발생: {e}")
        return None
    finally:
        db.close()
