"""Windows: amíg ez a folyamat fut, a gép ne aludjon el tétlenség miatt (a beállításokat nem módosítja;
a kérés a folyamat végén magától megszűnik). Más rendszeren nem csinál semmit."""
import sys


def keep_awake() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    except Exception:  # noqa: BLE001
        return False
