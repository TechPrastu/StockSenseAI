import logging
import os

class StockSenseAILogger:
    LOG_DIR = "logs"
    LOG_FILE = "stocksenseai.log"

    @staticmethod
    def get_logger(name="StockSenseAI"):
        if not os.path.exists(StockSenseAILogger.LOG_DIR):
            os.makedirs(StockSenseAILogger.LOG_DIR)
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler = logging.FileHandler(
                os.path.join(StockSenseAILogger.LOG_DIR, StockSenseAILogger.LOG_FILE)
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        return logger
