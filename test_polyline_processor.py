import polyline

from run_page.polyline_processor import start_end_hiding


def test_zero_hiding_distance_preserves_all_points():
    points = [(31.0, 118.0), (31.1, 118.1), (31.2, 118.2)]

    assert start_end_hiding(points, 0) == points


def test_positive_hiding_distance_trims_route_ends():
    points = polyline.decode("_ibE_seK_pR_pR_pR_pR")

    assert len(start_end_hiding(points, 1)) < len(points)
