import time
import logging
from datetime import datetime
from src.database.connection import initialize_db
from src.modules.metrics.system_task import (
    collect_cpu_metrics,
    collect_memory_metrics,
    collect_disk_metrics,
    collect_network_metrics,
)
from src.modules.metrics.docker_task import collect_docker_metrics
from src.modules.runtime.tmux_task import collect_runtime_status

# 로깅 설정 (INFO 레벨로 설정하여 주요 흐름 확인)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')

def main():
    # 🚀 시작 시 DB 구조부터 잡기 (기존 데이터 삭제됨)
    initialize_db()
    
    logging.info("서버 에이전트 가동 시작 (T1: 10s, T2: 60s, T3: 1h)")
    
    count_t2 = 0
    count_t3 = 0
    
    try:
        while True:
            # 1. 기준 시각 생성 (모든 수집기가 공유하여 조인 최적화)
            now = datetime.now()
            batch_id = now.isoformat()
            
            # ------------------------------------------------------------------
            # [Tier 1] 실시간 메트릭 (10초 주기)
            # ------------------------------------------------------------------
            res_cpu = collect_cpu_metrics(ts=now, batch_id=batch_id)
            res_mem = collect_memory_metrics(ts=now, batch_id=batch_id)
            res_disk = collect_disk_metrics(ts=now, batch_id=batch_id)
            res_net = collect_network_metrics(ts=now, batch_id=batch_id)
            res_doc = collect_docker_metrics(ts=now, batch_id=batch_id)
            
            if res_cpu: logging.info(f"[Tier 1] {res_cpu}")
            if res_mem: logging.info(f"[Tier 1] {res_mem}")
            if res_disk: logging.info(f"[Tier 1] {res_disk}")
            if res_net: logging.info(f"[Tier 1] {res_net}")
            if res_doc: logging.info(f"[Tier 1] {res_doc}")
            
            # ------------------------------------------------------------------
            # [Tier 2] 상태/환경 정보 (60초 주기: 10초 * 6)
            # ------------------------------------------------------------------
            if count_t2 % 6 == 0:
                res_run = collect_runtime_status(ts=now, batch_id=batch_id)
                if res_run: logging.info(f"[Tier 2] {res_run}")
            
            # ------------------------------------------------------------------
            # [Tier 3] 저빈도/통계 데이터 (1시간 주기: 10초 * 360)
            # 디스크 부하 방지 및 예측용 장기 데이터
            # ------------------------------------------------------------------
            if count_t3 % 360 == 0:
                # TODO: Tier 3 장기 통계 수집기 연결 (예: 월간 추세 집계 등)
                logging.info(f"[Tier 3] Skip (Placeholder)")
                pass
            
            # 카운터 관리 (오버플로우 방지)
            count_t2 += 1
            count_t3 += 1
            if count_t2 >= 60: count_t2 = 0
            if count_t3 >= 3600: count_t3 = 0 # 10시간 주기까지 커버 가능
            
            time.sleep(10)
            
    except KeyboardInterrupt:
        logging.info("에이전트 종료")
    except Exception as e:
        logging.error(f"메인 루프 치명적 오류: {e}")

if __name__ == "__main__":
    main()
