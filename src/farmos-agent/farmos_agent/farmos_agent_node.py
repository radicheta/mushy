"""
FarmOS daily report agent — ROS2 lifecycle node.

Lifecycle: configure (load creds, connect DB, auth FarmOS) ->
           activate (start APScheduler CronTrigger at 06:00) ->
           execute_report (observe -> synthesize -> record).

Per D-08: this container is the architectural seed for autonomous farm agents.
Per D-11: passive reporting agent only — no actuation in this phase.
Per T-13-06: credentials NEVER logged. Logger used only for status messages.
"""

import os
import datetime
import requests

from zoneinfo import ZoneInfo

import psycopg2
import rclpy
from rclpy.lifecycle import Node, TransitionCallbackReturn

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from farmos_agent.farmos_client import (
    get_session,
    get_asset_uuid,
    upload_photo,
    create_observation,
    observation_exists_for_date,
)
from farmos_agent.telemetry_query import query_daily_summary
from farmos_agent.report_builder import build_report_markdown


class FarmOSAgent(Node):
    """ROS2 lifecycle node that posts a daily observation to FarmOS."""

    def __init__(self):
        super().__init__('farmos_agent')
        self._scheduler = None
        self._db_conn = None
        self._session = None
        self._asset_uuid = None
        self._farmos_url = None
        self._farmos_username = None
        self._farmos_password = None
        self._tz = None
        self._bridge_url = None

    # ------------------------------------------------------------------
    # Lifecycle callbacks
    # ------------------------------------------------------------------

    def on_configure(self, state) -> TransitionCallbackReturn:
        """
        Load env vars, open TimescaleDB connection, authenticate to FarmOS,
        and cache the FC-1 asset UUID.
        """
        try:
            self._farmos_url = os.environ.get('FARMOS_URL', 'http://10.68.155.50:8082')
            self._farmos_username = os.environ['FARMOS_USERNAME']
            self._farmos_password = os.environ['FARMOS_PASSWORD']
            timescale_host = os.environ.get('TIMESCALE_HOST', 'localhost')
            timescale_password = os.environ['TIMESCALE_PASSWORD']
            self._tz = os.environ.get('REPORT_TIMEZONE', 'America/Toronto')
            self._bridge_url = os.environ.get('BRIDGE_URL', 'http://localhost:8081')

            # Open TimescaleDB connection (T-13-07: connect_timeout prevents hangs)
            self._db_conn = psycopg2.connect(
                host=timescale_host,
                port=5432,
                dbname='postgres',
                user='postgres',
                password=timescale_password,
                connect_timeout=10,
            )

            # Authenticate to FarmOS
            self._session = get_session(
                self._farmos_url,
                self._farmos_username,
                self._farmos_password,
            )

            # Cache FC-1 UUID on startup so execute_report() is fast
            self._asset_uuid = get_asset_uuid(self._session, self._farmos_url, 'FC-1')
            if self._asset_uuid:
                self.get_logger().info(
                    f'[farmos_agent] configured — FC-1 UUID: {self._asset_uuid}'
                )
            else:
                self.get_logger().warning(
                    '[farmos_agent] configured — FC-1 asset not found in FarmOS; '
                    'UUID will be resolved at report time'
                )

            return TransitionCallbackReturn.SUCCESS

        except KeyError as exc:
            self.get_logger().error(f'[farmos_agent] configure failed — missing env var: {exc}')
            return TransitionCallbackReturn.FAILURE
        except Exception as exc:
            self.get_logger().error(f'[farmos_agent] configure failed: {exc}')
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state) -> TransitionCallbackReturn:
        """Start the APScheduler CronTrigger at 06:00 local time (TZ set via env/container)."""
        try:
            self._scheduler = BackgroundScheduler()
            self._scheduler.add_job(
                self.execute_report,
                CronTrigger(hour=6, minute=0),
                id='daily_report',
                replace_existing=True,
            )
            self._scheduler.start()
            self.get_logger().info(
                '[farmos_agent] activated — daily report scheduled at 06:00'
            )
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            self.get_logger().error(f'[farmos_agent] activate failed: {exc}')
            return TransitionCallbackReturn.FAILURE

    def on_deactivate(self, state) -> TransitionCallbackReturn:
        """Shut down scheduler and close DB connection cleanly."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        if self._db_conn:
            try:
                self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None
        self.get_logger().info('[farmos_agent] deactivated')
        return TransitionCallbackReturn.SUCCESS

    # ------------------------------------------------------------------
    # Core reporting logic
    # ------------------------------------------------------------------

    def execute_report(self):
        """
        Observe -> Synthesize -> Record loop for the previous calendar day.

        Wrapped in try/except so failures are logged but do NOT crash the
        node or scheduler (T-13-07).
        """
        try:
            self._do_execute_report()
        except Exception as exc:
            self.get_logger().error(f'[farmos_agent] execute_report failed: {exc}')

    def _do_execute_report(self):
        tz = ZoneInfo(self._tz)
        report_date = (datetime.datetime.now(tz) - datetime.timedelta(days=1)).date()
        date_str = report_date.strftime('%Y-%m-%d')
        self.get_logger().info(f'[farmos_agent] running report for {date_str}')

        # Re-auth if session is stale (T-13-07)
        session = self._get_session_with_retry()

        # Resolve FC-1 UUID if not cached
        asset_uuid = self._asset_uuid
        if not asset_uuid:
            asset_uuid = get_asset_uuid(session, self._farmos_url, 'FC-1')
            if not asset_uuid:
                self.get_logger().error(
                    '[farmos_agent] FC-1 asset not found in FarmOS — skipping report'
                )
                return
            self._asset_uuid = asset_uuid

        # Duplicate check (D-09) — idempotent on restart
        if observation_exists_for_date(session, self._farmos_url, date_str):
            self.get_logger().info(
                f'[farmos_agent] observation for {date_str} already exists — skipping'
            )
            return

        # ------------------------------------------------------------------
        # OBSERVE
        # ------------------------------------------------------------------

        # TimescaleDB telemetry aggregation
        summary = query_daily_summary(self._db_conn, report_date, self._tz)

        # Camera snapshot — try bridge first, fall back to disk
        jpeg_bytes = self._fetch_camera_snapshot(date_str)

        # ------------------------------------------------------------------
        # SYNTHESIZE
        # ------------------------------------------------------------------
        markdown_notes = build_report_markdown(summary)

        # ------------------------------------------------------------------
        # RECORD
        # ------------------------------------------------------------------
        file_id = None
        if jpeg_bytes:
            file_id = upload_photo(
                session,
                self._farmos_url,
                jpeg_bytes,
                f'fc1-{date_str}.jpg',
            )
            if file_id:
                self.get_logger().info(f'[farmos_agent] photo uploaded — file_id: {file_id}')
            else:
                self.get_logger().warning('[farmos_agent] photo upload failed — continuing without image')

        obs_name = f'FC-1 Daily Report {date_str}'
        obs_uuid = create_observation(
            session,
            self._farmos_url,
            asset_uuid,
            obs_name,
            markdown_notes,
            file_id,
        )
        self.get_logger().info(
            f'[farmos_agent] observation created — {obs_name} ({obs_uuid})'
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_session_with_retry(self) -> requests.Session:
        """Return current session, refreshing if a quick HEAD test returns 401."""
        try:
            resp = self._session.get(
                f'{self._farmos_url}/api',
                timeout=5,
            )
            if resp.status_code == 401:
                raise requests.HTTPError(response=resp)
            return self._session
        except requests.HTTPError:
            self.get_logger().info('[farmos_agent] re-authenticating to FarmOS')
            self._session = get_session(
                self._farmos_url,
                self._farmos_username,
                self._farmos_password,
            )
            return self._session
        except Exception:
            # Network hiccup — return existing session and let the caller fail naturally
            return self._session

    def _fetch_camera_snapshot(self, date_str: str) -> bytes | None:
        """
        Fetch the latest camera frame.

        Primary:  GET {BRIDGE_URL}/camera/latest.jpg  (T-13-07: 10s timeout)
        Fallback: most recent JPEG from /data/snapshots/fc1/{date_str}/
        """
        try:
            resp = requests.get(
                f'{self._bridge_url}/camera/latest.jpg',
                timeout=10,
            )
            if resp.ok:
                self.get_logger().info('[farmos_agent] camera snapshot fetched from bridge')
                return resp.content
            # 503 or other error — fall through to disk
            self.get_logger().warning(
                f'[farmos_agent] bridge returned {resp.status_code} — trying disk fallback'
            )
        except Exception as exc:
            self.get_logger().warning(
                f'[farmos_agent] bridge snapshot fetch failed ({exc}) — trying disk fallback'
            )

        # Disk fallback: pick the most recent JPEG for the date
        snapshot_dir = f'/data/snapshots/fc1/{date_str}'
        if os.path.isdir(snapshot_dir):
            jpegs = sorted(
                f for f in os.listdir(snapshot_dir) if f.lower().endswith('.jpg')
            )
            if jpegs:
                path = os.path.join(snapshot_dir, jpegs[-1])
                with open(path, 'rb') as fh:
                    self.get_logger().info(
                        f'[farmos_agent] camera snapshot loaded from disk: {path}'
                    )
                    return fh.read()

        self.get_logger().warning(
            f'[farmos_agent] no camera snapshot available for {date_str} — report will have no image'
        )
        return None


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    rclpy.init()
    node = FarmOSAgent()

    # Self-transition — no external lifecycle manager in this container.
    # Call on_configure / on_activate directly (A2 fallback from RESEARCH.md).
    cfg_result = node.on_configure(None)
    if cfg_result != TransitionCallbackReturn.SUCCESS:
        node.get_logger().error('[farmos_agent] configure failed — exiting')
        node.destroy_node()
        rclpy.shutdown()
        return

    act_result = node.on_activate(None)
    if act_result != TransitionCallbackReturn.SUCCESS:
        node.get_logger().error('[farmos_agent] activate failed — exiting')
        node.destroy_node()
        rclpy.shutdown()
        return

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.on_deactivate(None)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
