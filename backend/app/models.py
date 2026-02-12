from sqlalchemy import Column, Text, Integer, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Message(Base):
    __tablename__ = 'nltosql'
    run_id = Column(Text, primary_key=True, index=True)
    thread_id = Column(Text, index=True)
    start_time = Column(Text)
    latency = Column(Float)
    input = Column(Text)
    is_user_authenticated = Column(Text)
    provinceName = Column(Text)
    culture = Column(Text)
    output = Column(Text)
    feedback = Column(Integer, default=0)
    status = Column(Text, default='error')
    corrected_sql = Column(Text, nullable=True)
    feedback_comment = Column(Text, nullable=True)
