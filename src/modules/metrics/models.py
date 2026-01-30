from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, BigInteger, Text, UniqueConstraint, Index
)
from sqlalchemy.sql import func
from src.database.connection import Base

# ------------------------------------------------------------
# 1. 메트릭 계열 (ops_metrics 스키마)
# ------------------------------------------------------------

class SystemMetric(Base):
    """
    서버 전체 주요 시스템 자원 스냅샷 (간단 요약본)
    """
    __tablename__ = "metrics_system"
    __table_args__ = {"schema": "ops_metrics", "comment": "서버 전체의 주요 시스템 자원 스냅샷"}

    id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각")

    # CPU
    cpu_user = Column(Float, comment="user CPU 사용률 (%)")
    cpu_system = Column(Float, comment="system CPU 사용률 (%)")
    cpu_iowait = Column(Float, comment="I/O wait CPU 비율 (%)")
    cpu_total = Column(Float, comment="전체 CPU 사용률 (%)")
    cpu_cores = Column(Integer, comment="서버 논리 코어 수")

    # 메모리
    ram_total_mb = Column(Float, comment="전체 메모리 용량 (MB)")
    ram_used_mb = Column(Float, comment="메모리 사용량 (MB)")
    ram_percent = Column(Float, comment="메모리 사용률 (%)")

    # Load Average
    load_1min = Column(Float, comment="1분 평균 부하량")
    load_5min = Column(Float, comment="5분 평균 부하량")
    load_15min = Column(Float, comment="15분 평균 부하량")


class CpuMetric(Base):
    """
    CPU 상세 메트릭
    """
    __tablename__ = "metrics_cpu"
    __table_args__ = {"schema": "ops_metrics", "comment": "CPU 상세 메트릭"}

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    core_count = Column(Integer, comment="논리 코어 수")
    cpu_percent = Column(Float, comment="전체 CPU 사용률 (%)")
    load_1min = Column(Float)
    load_5min = Column(Float)
    load_15min = Column(Float)


class MemoryMetric(Base):
    """
    메모리 상세 정보
    """
    __tablename__ = "metrics_memory"
    __table_args__ = {"schema": "ops_metrics", "comment": "메모리 상세 메트릭"}

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    mem_total_mb = Column(Float, comment="총 메모리 (MB)")
    mem_used_mb = Column(Float, comment="사용 중 메모리 (MB)")
    mem_free_mb = Column(Float, comment="여유 메모리 (MB)")
    mem_percent = Column(Float, comment="메모리 사용률 (%)")
    swap_total_mb = Column(Float, comment="총 스왑 메모리 (MB)")
    swap_used_mb = Column(Float, comment="사용 중 스왑 메모리 (MB)")


class DiskMetric(Base):
    """
    마운트 포인트별 디스크 사용량
    """
    __tablename__ = "metrics_disk"
    __table_args__ = {"schema": "ops_metrics", "comment": "디스크 사용량 메트릭"}

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    mount = Column(Text, nullable=False, comment="마운트 지점 (예: /, /home)")
    disk_total_gb = Column(Float, comment="총 디스크 용량 (GB)")
    disk_used_gb = Column(Float, comment="사용 중 디스크 용량 (GB)")
    disk_free_gb = Column(Float, comment="여유 디스크 용량 (GB)")
    disk_percent = Column(Float, comment="디스크 사용률 (%)")


Index("idx_disk_mount", DiskMetric.mount)


class NetworkMetric(Base):
    """
    네트워크 인터페이스별 트래픽 메트릭
    """
    __tablename__ = "metrics_network"
    __table_args__ = {"schema": "ops_metrics", "comment": "네트워크 트래픽 메트릭"}

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    interface = Column(Text, nullable=False, comment="네트워크 인터페이스명 (eth0 등)")
    rx_bytes = Column(BigInteger, comment="누적 수신 바이트")
    tx_bytes = Column(BigInteger, comment="누적 송신 바이트")
    rx_rate_bps = Column(Float, comment="초당 수신 bps")
    tx_rate_bps = Column(Float, comment="초당 송신 bps")


Index("idx_network_interface", NetworkMetric.interface)


class DockerMetric(Base):
    """
    도커 컨테이너별 자원 사용량 스냅샷
    """
    __tablename__ = "docker_metrics"
    __table_args__ = (
        UniqueConstraint("ts", "container_id", name="uq_docker_metrics_ts_container"),
        {"schema": "ops_metrics", "comment": "개별 도커 컨테이너의 자원 사용량"},
    )

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    container_id = Column(Text, nullable=False, comment="도커 컨테이너 ID")
    container_name = Column(Text, nullable=False, index=True, comment="도커 컨테이너 이름")

    cpu_percent = Column(Float, comment="컨테이너 CPU 사용률 (%)")
    mem_used_mb = Column(Float, comment="컨테이너 메모리 사용량 (MB)")
    mem_percent = Column(Float, comment="컨테이너 메모리 사용률 (%)")


class DockerImage(Base):
    """
    도커 이미지 상태 (정리 대상 판단용)
    """
    __tablename__ = "docker_images"
    __table_args__ = {"schema": "ops_metrics", "comment": "도커 이미지 상태 정보"}

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    image_id = Column(Text, nullable=False, comment="이미지 ID")
    repo = Column(Text, comment="리포지터리명")
    tag = Column(Text, comment="태그명")
    size_mb = Column(Float, comment="이미지 용량 (MB)")

    last_used_at = Column(DateTime(timezone=True), comment="마지막 사용 시각 (추정)")
    unused_days = Column(Integer, comment="마지막 사용 이후 경과 일수 (추정)")


Index("idx_docker_images_image", DockerImage.image_id)
