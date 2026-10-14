import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import launch


def test_existing_ready_environment_does_not_install(monkeypatch,tmp_path):
    env=tmp_path / "existing env"
    monkeypatch.setattr(launch,"base_candidates",lambda:[])
    monkeypatch.setattr(launch,"conda_command",lambda roots:None)
    monkeypatch.setattr(launch,"locate_environment",lambda roots,command:env)
    monkeypatch.setattr(launch,"dependencies_ready",lambda python:True)
    monkeypatch.setattr(launch.subprocess,"run",lambda *a,**k:pytest.fail("Must not install for a ready environment"))
    assert launch.prepare_environment()==env


def test_missing_environment_is_created_then_detected(monkeypatch,tmp_path):
    env=tmp_path / "new env"
    located=iter([None,env])
    calls=[]
    monkeypatch.setattr(launch,"base_candidates",lambda:[])
    monkeypatch.setattr(launch,"conda_command",lambda roots:["base-python","-m","conda"])
    monkeypatch.setattr(launch,"locate_environment",lambda roots,command:next(located))
    monkeypatch.setattr(launch,"dependencies_ready",lambda python:True)
    monkeypatch.setattr(launch.subprocess,"run",lambda command,**kwargs:calls.append(command))
    assert launch.prepare_environment()==env
    assert calls[0][:5]==["base-python","-m","conda","env","create"]
    assert "--file" in calls[0] and "--yes" in calls[0]


def test_missing_dependencies_are_repaired(monkeypatch,tmp_path):
    env=tmp_path / "environment with spaces"
    checks=iter([False,True])
    calls=[]
    monkeypatch.setattr(launch,"base_candidates",lambda:[])
    monkeypatch.setattr(launch,"conda_command",lambda roots:["base-python","-m","conda"])
    monkeypatch.setattr(launch,"locate_environment",lambda roots,command:env)
    monkeypatch.setattr(launch,"dependencies_ready",lambda python:next(checks))
    monkeypatch.setattr(launch.subprocess,"run",lambda command,**kwargs:calls.append(command))
    assert launch.prepare_environment()==env
    assert calls[0][3:6]==["install","--prefix",str(env)]
    assert calls[1][:4]==[str(env/"python.exe"),"-m","pip","install"]


def test_missing_conda_is_reported(monkeypatch):
    monkeypatch.setattr(launch,"base_candidates",lambda:[])
    monkeypatch.setattr(launch,"conda_command",lambda roots:None)
    monkeypatch.setattr(launch,"locate_environment",lambda roots,command:None)
    with pytest.raises(RuntimeError,match="Conda was not found"):
        launch.prepare_environment()
