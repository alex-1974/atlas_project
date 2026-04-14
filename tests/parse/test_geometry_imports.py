def test_geometry_imports():
    import atlas.parse.geometry as geometry
    import atlas.parse.zones as zones

    assert geometry is not None
    assert zones is not None
