"""
Docker 메트릭 수집 모듈 (CLI 버전)

파이썬 docker 라이브러리 대신, subprocess를 통해 docker CLI를 직접 호출합니다.
이 방식은 서버의 도커 컨텍스트 설정과 무관하게 작동합니다.
"""
import subprocess
import json
import logging
from datetime import datetime
from src.database.connection import SessionLocal
from .models import DockerMetric

logger = logging.getLogger("DOCKER")


def collect_docker_metrics(ts=None, batch_id=None):
    """
    docker CLI를 통해 실행 중인 컨테이너의 지표를 수집하여 DB에 저장합니다.
    ts: main.py에서 전달받은 동기화된 타임스탬프
    """
    if ts is None:
        ts = datetime.now()
    batch_id = batch_id or ts.isoformat()

    db = SessionLocal()
    try:
        # docker stats 명령어 실행 (JSON 형식으로 1회 스냅샷)
        # --no-stream 옵션으로 1회만 출력하고 종료
        # --format으로 JSON 형태로 출력
        cmd = [
            'docker', 'stats', '--no-stream', 
            '--format', '{{json .}}'
        ]
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=30
        )
        
        if result.returncode != 0:
            logger.error(f"docker stats 명령 실패: {result.stderr}")
            return None
            
        if not result.stdout.strip():
            logger.info("실행 중인 컨테이너가 없습니다.")
            return "Docker: 0 containers"

        metrics_to_save = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                
                # CPU 사용률 파싱 (예: "0.50%")
                cpu_str = data.get('CPUPerc', '0%').replace('%', '')
                cpu_percent = float(cpu_str) if cpu_str else 0.0
                
                # 메모리 사용량 파싱 (예: "50MiB / 7.66GiB")
                mem_str = data.get('MemUsage', '0MiB / 0GiB')
                mem_used_str = mem_str.split('/')[0].strip()
                
                # MiB, GiB, KiB 단위 처리
                mem_used_mb = 0.0
                if 'GiB' in mem_used_str:
                    mem_used_mb = float(mem_used_str.replace('GiB', '').strip()) * 1024
                elif 'MiB' in mem_used_str:
                    mem_used_mb = float(mem_used_str.replace('MiB', '').strip())
                elif 'KiB' in mem_used_str:
                    mem_used_mb = float(mem_used_str.replace('KiB', '').strip()) / 1024
                
                # 메모리 퍼센트 파싱 (예: "0.64%")
                mem_percent_str = data.get('MemPerc', '0%').replace('%', '')
                mem_percent = float(mem_percent_str) if mem_percent_str else 0.0
                
                new_metric = DockerMetric(
                    ts=ts,
                    batch_id=batch_id,
                    container_id=data.get('ID', 'unknown')[:12],
                    container_name=data.get('Name', 'unknown'),
                    cpu_percent=cpu_percent,
                    mem_used_mb=mem_used_mb,
                    mem_percent=mem_percent
                )
                metrics_to_save.append(new_metric)
                
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(f"컨테이너 데이터 파싱 실패: {e}")
                continue

        if metrics_to_save:
            db.bulk_save_objects(metrics_to_save)
            db.commit()
            logger.info(f"도커 지표 저장 완료 ({len(metrics_to_save)}개 컨테이너)")
            return f"Docker: {len(metrics_to_save)} containers collected"
        
        return "Docker: 0 containers"
        
    except subprocess.TimeoutExpired:
        logger.error("docker stats 명령이 시간 초과되었습니다.")
        return None
    except FileNotFoundError:
        logger.error("docker 명령을 찾을 수 없습니다. 컨테이너에 docker CLI가 설치되어 있는지 확인하세요.")
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"도커 수집 중 오류 발생: {e}")
        return None
    finally:
        db.close()
