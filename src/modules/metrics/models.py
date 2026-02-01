from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, BigInteger, Text, UniqueConstraint, Index
)
from sqlalchemy.sql import func
from src.database.connection import Base

# ------------------------------------------------------------
# 1. 메트릭 계열 (ops_metrics 스키마)
# ------------------------------------------------------------

class CpuMetric(Base):
    """
    CPU 상세 메트릭
    """
    __tablename__ = "metrics_cpu"
    __table_args__ = {
        "schema": "ops_metrics",
        "comment": "CPU 사용률과 부하(load average) 등을 저장하는 상세 테이블. 시간(ts) 기준으로 조회/집계한다.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK). 조인에는 사용하지 않음.")
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")
    batch_id = Column(Text, index=True, comment="동일 수집 사이클 식별자. ts 미세 오차로 조인이 실패하는 것을 방지하기 위해 사용.")

    core_count = Column(Integer, comment="논리 코어 수.")
    cpu_percent = Column(Float, comment="전체 CPU 사용률(%).")
    cpu_user = Column(Float, comment="사용자 영역 CPU 사용률(%).")
    cpu_system = Column(Float, comment="커널/시스템 영역 CPU 사용률(%).")
    cpu_iowait = Column(Float, comment="I/O 대기 CPU 비율(%).")
    load_1min = Column(Float, comment="1분 평균 부하(load average).")
    load_5min = Column(Float, comment="5분 평균 부하(load average).")
    load_15min = Column(Float, comment="15분 평균 부하(load average).")


class MemoryMetric(Base):
    """
    메모리 상세 정보
    """
    __tablename__ = "metrics_memory"
    __table_args__ = {
        "schema": "ops_metrics",
        "comment": "RAM과 Swap 사용량을 저장하는 상세 테이블. 시간(ts) 기준으로 조회/집계한다.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK). 조인에는 사용하지 않음.")
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")
    batch_id = Column(Text, index=True, comment="동일 수집 사이클 식별자. ts 미세 오차로 조인이 실패하는 것을 방지하기 위해 사용.")

    mem_total_mb = Column(Float, comment="총 메모리 용량(MB).")
    mem_used_mb = Column(Float, comment="사용 중 메모리(MB).")
    mem_free_mb = Column(Float, comment="여유 메모리(MB).")
    mem_percent = Column(Float, comment="메모리 사용률(%).")
    mem_cached_mb = Column(Float, comment="캐시 메모리(MB).")
    mem_buffers_mb = Column(Float, comment="버퍼 메모리(MB).")
    swap_total_mb = Column(Float, comment="총 스왑 메모리(MB).")
    swap_used_mb = Column(Float, comment="사용 중 스왑 메모리(MB).")


class DiskMetric(Base):
    """
    마운트 포인트별 디스크 사용량
    """
    __tablename__ = "metrics_disk"
    __table_args__ = {
        "schema": "ops_metrics",
        "comment": "마운트 지점별 디스크 사용량을 저장하는 테이블.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK). 조인에는 사용하지 않음.")
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")
    batch_id = Column(Text, index=True, comment="동일 수집 사이클 식별자. ts 미세 오차로 조인이 실패하는 것을 방지하기 위해 사용.")

    mount = Column(Text, nullable=False, comment="마운트 지점(예: /, /home).")
    disk_total_gb = Column(Float, comment="총 디스크 용량(GB).")
    disk_used_gb = Column(Float, comment="사용 중 디스크 용량(GB).")
    disk_free_gb = Column(Float, comment="여유 디스크 용량(GB).")
    disk_percent = Column(Float, comment="디스크 사용률(%).")


Index("idx_disk_mount", DiskMetric.mount)


class NetworkMetric(Base):
    """
    네트워크 인터페이스별 트래픽 메트릭
    """
    __tablename__ = "metrics_network"
    __table_args__ = {
        "schema": "ops_metrics",
        "comment": "네트워크 인터페이스별 트래픽을 저장하는 테이블.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK). 조인에는 사용하지 않음.")
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")
    batch_id = Column(Text, index=True, comment="동일 수집 사이클 식별자. ts 미세 오차로 조인이 실패하는 것을 방지하기 위해 사용.")

    interface = Column(Text, nullable=False, comment="네트워크 인터페이스명(예: eth0).")
    rx_bytes = Column(BigInteger, comment="누적 수신 바이트.")
    tx_bytes = Column(BigInteger, comment="누적 송신 바이트.")
    rx_rate_bps = Column(Float, comment="초당 수신 속도(bps).")
    tx_rate_bps = Column(Float, comment="초당 송신 속도(bps).")


Index("idx_network_interface", NetworkMetric.interface)


class DockerMetric(Base):
    """
    도커 컨테이너별 자원 사용량 스냅샷
    """
    __tablename__ = "docker_metrics"
    __table_args__ = (
        UniqueConstraint("ts", "container_id", name="uq_docker_metrics_ts_container"),
        {"schema": "ops_metrics", "comment": "도커 컨테이너별 CPU/메모리 사용량 스냅샷 테이블."},
    )

    id = Column(Integer, primary_key=True, comment="행 식별자(PK). 조인에는 사용하지 않음.")
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")
    batch_id = Column(Text, index=True, comment="동일 수집 사이클 식별자. ts 미세 오차로 조인이 실패하는 것을 방지하기 위해 사용.")

    container_id = Column(Text, nullable=False, comment="도커 컨테이너 ID.")
    container_name = Column(Text, nullable=False, index=True, comment="도커 컨테이너 이름.")

    cpu_percent = Column(Float, comment="컨테이너 CPU 사용률(%).")
    mem_used_mb = Column(Float, comment="컨테이너 메모리 사용량(MB).")
    mem_percent = Column(Float, comment="컨테이너 메모리 사용률(%).")
