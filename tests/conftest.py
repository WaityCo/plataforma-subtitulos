import sys
from pathlib import Path

# Permite importar `engine` aunque pytest no se lance desde la raíz del proyecto.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
