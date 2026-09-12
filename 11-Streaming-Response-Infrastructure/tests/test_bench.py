import argparse

from stream import bench


async def test_run_once_fake_returns_a_ttft() -> None:
    ttft = await bench._run_once("fake", "fake", think=False)

    assert ttft is not None
    assert ttft >= 0


async def test_main_async_fake_prints_percentiles(capsys) -> None:
    args = argparse.Namespace(provider="fake", model="fake", n=3, think=False)

    await bench._main_async(args)

    out = capsys.readouterr().out
    assert "p50 TTFT" in out
    assert "p95 TTFT" in out


def test_percentile_single_value() -> None:
    assert bench._percentile([42.0], 95) == 42.0


def test_percentile_matches_linear_interpolation() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]

    assert bench._percentile(values, 50) == 30.0
