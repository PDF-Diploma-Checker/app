import logging
import llama_cpp

logger = logging.getLogger(__name__)


def check_cuda():
    logger.info("Sprawdzanie informacji o systemie z llama.cpp...")

    try:
        sys_info = llama_cpp.llama_print_system_info().decode('utf-8')
    except Exception:
        logger.exception("Failed to read llama.cpp system info")
        raise

    logger.info("\n--- SUROWE DANE ---")
    logger.info(sys_info)
    logger.info("-------------------\n")
    
    if "CUDA = 1" in sys_info:
        logger.info(" SUKCES: Twoja biblioteka llama-cpp-python WIDZI kartę graficzną (CUDA)!")
    else:
        logger.info(" BŁĄD: Twoja biblioteka jest skompilowana TYLKO na procesor (CPU).")
        logger.info("Parametr n_gpu_layers będzie ignorowany.")

if __name__ == "__main__":
    check_cuda()