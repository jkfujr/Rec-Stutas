# core/logs.py

import os
import logging
from logging.handlers import TimedRotatingFileHandler

def log():
    """
    初始化日志记录器，仅配置文件处理器，记录 DEBUG 及以上级别的日志。
    """
    logger = logging.getLogger()
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.DEBUG)

    script_directory = os.path.dirname(os.path.abspath(__file__))
    log_directory = os.path.abspath(os.path.join(script_directory, '..', 'logs'))
    
    if not os.path.exists(log_directory):
        try:
            os.makedirs(log_directory)
        except Exception as e:
            log_print(f"[日志] 创建日志目录 {log_directory} 失败: {e}")

    default_log_file_name = "BCK"
    log_file_path = os.path.join(log_directory, default_log_file_name)

    file_handler = TimedRotatingFileHandler(
        log_file_path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(processName)s - %(message)s"
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger

def log_print(message, level="INFO"):
    """
    记录日志并输出到控制台。

    参数:
    - message (str): 需要记录的消息内容。
    - level (str): 日志等级，默认为 'INFO'。可以设置为 'DEBUG'，'INFO'，'WARNING'，'ERROR'，'CRITICAL'。
    """
    logger = logging.getLogger()
    
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logger.log(level, message)
    level_name = logging.getLevelName(level)
    prefix = f"{level_name}:     "
    print(prefix + message)
