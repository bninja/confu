import confu


def test_interface():
    assert confu.__all__ == [
        'ansible',
        'aws',
        'cfn',
        'cli',
        'pkg',
        'settings',
    ]
