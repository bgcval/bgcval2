"""Test funcs in analysis_timeseries."""
import os
import pytest
import yaml

from bgcval2.analysis_timeseries import load_function

def test_load_function(tmp_path):
    """Test load_function()."""
    dummy_func_file = tmp_path / 'myfuncfile.py'
    with open(dummy_func_file, "w") as fil:
        fil.write("import os\n\ndef myfunc():\n    return 22\n")
    convert = {"path": str(dummy_func_file), "function": "myfunc"}
    expected_func, expected_kwargs = load_function(convert)
    res = expected_func()
    assert res == 22
    assert expected_kwargs == {}


def test_load_function_kwargs(tmp_path):
    """Test load_function()."""
    dummy_func_file = tmp_path / 'myfuncfile2.py'
    with open(dummy_func_file, "w") as fil:
        fil.write("import bgcval2\n\ndef myfunc():\n    return 22\n")
    convert = {
        "path": str(dummy_func_file), "function": "myfunc",
        "cow": "moo"}
    expected_func, expected_kwargs = load_function(convert)
    res = expected_func()
    assert res == 22
    assert expected_kwargs == {"cow": "moo"}
