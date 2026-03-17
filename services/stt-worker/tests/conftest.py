# services/stt-worker/tests/conftest.py
import os
import tempfile

# Settings() e instanțiat la import-time în config.py.
# DATABASE_URL și AUDIO_STORAGE_PATH sunt obligatorii.
# Le setăm înainte de orice import din src/.
#
# tempfile.gettempdir() = directorul temp al OS-ului:
#   Linux/Mac: /tmp
#   Windows:   C:\Users\...\AppData\Local\Temp
# Există mereu → validatorul audio_path_must_exist() trece.
_tmp = tempfile.gettempdir()
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("AUDIO_STORAGE_PATH", _tmp)
os.environ.setdefault("WHISPER_MODEL_PATH", os.path.join(_tmp, "whisper_models_test"))
