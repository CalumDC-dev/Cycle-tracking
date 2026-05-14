import json
import gzip
import struct
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from workout_tracker.activity_import import load_activity_file


class ActivityImportTests(unittest.TestCase):
    def test_load_activity_csv_maps_strava_style_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activities.csv"
            path.write_text(
                "Activity ID,Activity Name,Activity Date,Elapsed Time,Distance,Average Heart Rate\n"
                "123,Kinomap free-ride,2026-05-12T06:15:00,00:05:00,8.4,128\n",
                encoding="utf-8",
            )

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "strava")
        self.assertEqual(rows[0]["source_activity_id"], "123")
        self.assertEqual(rows[0]["title"], "Kinomap free-ride")
        self.assertEqual(rows[0]["started_on"], "2026-05-12T06:15:00")
        self.assertEqual(rows[0]["duration_seconds"], "300")
        self.assertEqual(rows[0]["raw_distance"], "8.4")
        self.assertEqual(rows[0]["hr"], "128")

    def test_load_strava_bulk_csv_preserves_first_duplicate_distance_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activities.csv"
            path.write_text(
                "Activity ID,Activity Date,Activity Name,Elapsed Time,Distance,Elapsed Time,Distance,Average Watts\n"
                '123,"May 12, 2026, 8:07:59 AM",Kinomap free-ride,4501,54.62,4501.0,54626.0,340\n',
                encoding="utf-8",
            )

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["started_on"], "2026-05-12T08:07:59")
        self.assertEqual(rows[0]["duration_seconds"], "4501")
        self.assertEqual(rows[0]["raw_distance"], "54.62")

    def test_load_activity_json_accepts_activity_list_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activities.json"
            path.write_text(
                json.dumps(
                    {
                        "activities": [
                            {
                                "id": "abc",
                                "name": "Lap attempt",
                                "start_date_local": "2026-05-12T07:00:00",
                                "moving_time": 240,
                                "distance": 4,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_activity_id"], "abc")
        self.assertEqual(rows[0]["title"], "Lap attempt")
        self.assertEqual(rows[0]["duration_seconds"], "240")
        self.assertEqual(rows[0]["raw_distance"], "4")

    def test_load_activity_tcx_maps_lap_summary_and_trackpoint_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Kinomap_Free_ride.tcx"
            path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
  xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
  <Activities>
    <Activity Sport="Biking">
      <Id>2026-05-12T08:07:58Z</Id>
      <Lap StartTime="2026-05-12T08:07:58Z">
        <TotalTimeSeconds>4502.2</TotalTimeSeconds>
        <DistanceMeters>54626</DistanceMeters>
        <Calories>1432</Calories>
        <Track>
          <Trackpoint>
            <Time>2026-05-12T08:07:59Z</Time>
            <Cadence>100</Cadence>
            <HeartRateBpm><Value>122</Value></HeartRateBpm>
            <Extensions><ns3:TPX><ns3:Speed>5</ns3:Speed><ns3:Watts>250</ns3:Watts></ns3:TPX></Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2026-05-12T08:08:00Z</Time>
            <Cadence>120</Cadence>
            <HeartRateBpm><Value>126</Value></HeartRateBpm>
            <Extensions><ns3:TPX><ns3:Speed>7</ns3:Speed><ns3:Watts>300</ns3:Watts></ns3:TPX></Extensions>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
""",
                encoding="utf-8",
            )

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_activity_id"], "2026-05-12T08:07:58Z")
        self.assertEqual(rows[0]["title"], "Kinomap Free ride")
        self.assertEqual(rows[0]["started_on"], "2026-05-12T08:07:58Z")
        self.assertEqual(rows[0]["duration_seconds"], "4502.2")
        self.assertEqual(rows[0]["raw_distance"], "54.626")
        self.assertEqual(rows[0]["hr"], "124")
        self.assertIn('"average_cadence": 110.0', rows[0]["raw_payload"])
        self.assertIn('"average_watts": 275.0', rows[0]["raw_payload"])
        self.assertIn('"analysis_version": 1', rows[0]["raw_payload"])
        self.assertIn('"max_speed_mps"', rows[0]["raw_payload"])
        self.assertIn('"trackpoint_count": 2', rows[0]["raw_payload"])

    def test_load_activity_tcx_gz(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activity.tcx.gz"
            tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Biking"><Id>2026-05-12T08:07:58Z</Id>
    <Lap StartTime="2026-05-12T08:07:58Z"><TotalTimeSeconds>60</TotalTimeSeconds><DistanceMeters>1000</DistanceMeters></Lap>
  </Activity></Activities>
</TrainingCenterDatabase>
"""
            path.write_bytes(gzip.compress(tcx.encode("utf-8")))

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_distance"], "1")
        self.assertEqual(rows[0]["duration_seconds"], "60")

    def test_load_strava_bulk_zip_merges_csv_metadata_with_tcx_gz_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "export_123.zip"
            tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
  xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
  <Activities>
    <Activity Sport="Biking">
      <Id>2026-05-12T08:07:58Z</Id>
      <Lap StartTime="2026-05-12T08:07:58Z">
        <TotalTimeSeconds>4502.2</TotalTimeSeconds>
        <DistanceMeters>54626</DistanceMeters>
        <Calories>1432</Calories>
        <Track><Trackpoint><Cadence>100</Cadence><Extensions><ns3:TPX><ns3:Watts>250</ns3:Watts></ns3:TPX></Extensions></Trackpoint></Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""
            activities_csv = (
                "Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename,Average Watts\n"
                '18474137768,"May 12, 2026, 8:07:59 AM",Kinomap - Free ride,Virtual Ride,4501,54.62,activities/19579407163.tcx.gz,340\n'
            )
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("activities.csv", activities_csv)
                archive.writestr("activities/19579407163.tcx.gz", gzip.compress(tcx.encode("utf-8")))

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_activity_id"], "18474137768")
        self.assertEqual(rows[0]["title"], "Kinomap - Free ride")
        self.assertEqual(rows[0]["started_on"], "2026-05-12T08:07:58Z")
        self.assertEqual(rows[0]["duration_seconds"], "4502.2")
        self.assertEqual(rows[0]["raw_distance"], "54.626")
        payload = json.loads(rows[0]["raw_payload"])
        self.assertEqual(payload["archive_format"], "strava_bulk_export")
        self.assertEqual(payload["activity_file"], "activities/19579407163.tcx.gz")
        self.assertEqual(payload["activity_type"], "Virtual Ride")
        self.assertEqual(payload["csv_average_watts"], 340.0)
        self.assertEqual(payload["average_watts"], 250.0)

    def test_load_activity_fit_maps_session_laps_and_record_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "14_May_2026_11_04.fit"
            path.write_bytes(fit_fixture())

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_activity_id"], "fit:305419896:2026-05-14T10:06:58Z")
        self.assertEqual(rows[0]["title"], "14 May 2026 11 04")
        self.assertEqual(rows[0]["started_on"], "2026-05-14T10:04:53Z")
        self.assertEqual(rows[0]["duration_seconds"], "122.003")
        self.assertEqual(rows[0]["raw_distance"], "1.67783")
        self.assertEqual(rows[0]["hr"], "122")
        payload = json.loads(rows[0]["raw_payload"])
        self.assertEqual(payload["format"], "fit")
        self.assertEqual(payload["sport"], "cycling")
        self.assertEqual(payload["sub_sport"], "indoor_cycling")
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["lap_count"], 2)
        self.assertEqual(payload["laps"][0]["distance_m"], 1008.98)
        self.assertEqual(payload["average_watts"], 275.0)
        self.assertEqual(payload["max_watts"], 300)
        self.assertEqual(payload["average_cadence"], 110.0)
        self.assertEqual(payload["average_source_hr"], 122.0)
        self.assertEqual(payload["session_average_watts"], 349)

    def test_load_strava_bulk_zip_merges_csv_metadata_with_fit_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "export_123.zip"
            activities_csv = (
                "Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename,Average Watts\n"
                '18474137769,"May 14, 2026, 11:04:53 AM",SuperCycle test,Virtual Ride,122,1.67,activities/123.fit,349\n'
            )
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("activities.csv", activities_csv)
                archive.writestr("activities/123.fit", fit_fixture())

            rows = load_activity_file(path, "strava")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_activity_id"], "18474137769")
        self.assertEqual(rows[0]["title"], "SuperCycle test")
        self.assertEqual(rows[0]["started_on"], "2026-05-14T10:04:53Z")
        payload = json.loads(rows[0]["raw_payload"])
        self.assertEqual(payload["activity_file"], "activities/123.fit")
        self.assertEqual(payload["csv_average_watts"], 349.0)
        self.assertEqual(payload["average_watts"], 275.0)


FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


def fit_fixture() -> bytes:
    start = fit_seconds("2026-05-14T10:04:53Z")
    created = fit_seconds("2026-05-14T10:06:58Z")
    data = b"".join(
        [
            fit_definition(0, 0, [(0, 1, 0x00), (3, 4, 0x86), (4, 4, 0x86)]),
            fit_data(0, "BI I", 4, 305419896, created),
            fit_definition(
                1,
                18,
                [
                    (253, 4, 0x86),
                    (2, 4, 0x86),
                    (5, 1, 0x00),
                    (6, 1, 0x00),
                    (7, 4, 0x86),
                    (8, 4, 0x86),
                    (9, 4, 0x86),
                    (11, 2, 0x84),
                    (14, 2, 0x84),
                    (15, 2, 0x84),
                    (18, 1, 0x02),
                    (19, 1, 0x02),
                    (20, 2, 0x84),
                    (21, 2, 0x84),
                    (26, 2, 0x84),
                ],
            ),
            fit_data(1, "IIBBIIIHHHBBHHH", start + 122, start, 2, 6, 122003, 122003, 167783, 42, 13752, 17422, 132, 175, 349, 458, 2),
            fit_definition(2, 19, [(253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (9, 4, 0x86)]),
            fit_data(2, "IIIII", start + 75, start, 75005, 75005, 100898),
            fit_data(2, "IIIII", start + 122, start + 75, 46998, 46998, 66885),
            fit_definition(3, 20, [(253, 4, 0x86), (5, 4, 0x86), (6, 2, 0x84), (7, 2, 0x84), (4, 1, 0x02), (3, 1, 0x02)]),
            fit_data(3, "IIHHBB", start + 1, 0, 5000, 250, 100, 120),
            fit_data(3, "IIHHBB", start + 2, 1000, 7000, 300, 120, 124),
        ]
    )
    header = struct.pack("<BBHI4sH", 14, 32, 21200, len(data), b".FIT", 0)
    return header + data + b"\0\0"


def fit_definition(local_num: int, global_num: int, fields: list[tuple[int, int, int]]) -> bytes:
    field_bytes = b"".join(struct.pack("<BBB", number, size, base_type) for number, size, base_type in fields)
    return bytes([0x40 | local_num]) + struct.pack("<BBHB", 0, 0, global_num, len(fields)) + field_bytes


def fit_data(local_num: int, fmt: str, *values: object) -> bytes:
    return bytes([local_num]) + struct.pack("<" + fmt.replace(" ", ""), *values)


def fit_seconds(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int((parsed - FIT_EPOCH).total_seconds())


if __name__ == "__main__":
    unittest.main()
