import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('campo_publish',Path(__file__).resolve().parents[1]/'packaging/publish_update.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
publish=module.publish
