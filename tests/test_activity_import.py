import json
import gzip
import tempfile
import unittest
import zipfile
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


if __name__ == "__main__":
    unittest.main()
