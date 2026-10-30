import pytest
from kintsugi.decorator import heal


def test_uninspectable_lambda_source_returns_raw():
    # Lambdas or dynamically generated functions that cannot be inspected by inspect.getsource
    raw_fn = lambda x: x + 10  # noqa: E731
    decorated = heal(cache_dir=None)(raw_fn)

    # Must return raw function and execute correctly
    assert decorated(5) == 15
    # Does not have __kintsugi_state__ attached because healing is safely disabled
    assert not hasattr(decorated, "__kintsugi_state__")
