import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class InjectionPlanningConfig(models.Model):
    _name = "injection.planning.config"
    _description = "사출 생산계획 설정"
    _rec_name = "id"

    # ── Oracle 연결 ──
    oracle_host = fields.Char(string="Oracle 호스트", default="59.3.91.1")
    oracle_port = fields.Integer(string="Oracle 포트", default=1521)
    oracle_sid = fields.Char(string="Oracle SID", default="orcl")
    oracle_user = fields.Char(string="DB 사용자", default="prd")
    oracle_password = fields.Char(string="DB 비밀번호", password=True)
    oracle_client_path = fields.Char(
        string="Oracle Client 경로",
        help="Oracle Instant Client 라이브러리 경로 (Thick 모드). "
             "예: /Users/user/instantclient_23_3 또는 /opt/oracle/instantclient_23_3",
    )
    hourly_table = fields.Char(
        string="시간대별 테이블", default="T_ZM_PLN1",
        help="시간대별 생산계획 Oracle 테이블명",
    )
    daily_table = fields.Char(
        string="일자별 테이블", default="T_ZM_PLN2",
        help="일자별 생산계획 Oracle 테이블명",
    )
    demand_query_daily = fields.Text(
        string="일별 수요 쿼리 (커스텀)",
        help="커스텀 SQL 쿼리. 비워두면 기본 테이블에서 조회",
    )
    demand_query_hourly = fields.Text(
        string="시간별 수요 쿼리 (커스텀)",
        help="커스텀 SQL 쿼리. 비워두면 기본 테이블에서 조회",
    )

    # ── 자동화 ──
    auto_generate_mo = fields.Boolean(
        string="자동 MO 생성",
        default=False,
        help="활성화 시 cron이 자동으로 계획 계산 + MO 생성",
    )
    planning_horizon = fields.Integer(
        string="계획 기간 (일)", default=14,
    )

    # ── 글로벌 기본값 ──
    default_changeover = fields.Float(
        string="기본 교체 시간 (시간)", default=2.0,
    )
    default_defect_rate = fields.Float(
        string="기본 불량율 (%)", default=2.0,
    )
    default_initial_scrap = fields.Integer(
        string="기본 초기 불량 (개)", default=20,
    )
    default_min_lot_size = fields.Integer(
        string="기본 최소 로트 (개)", default=100,
    )

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    def _get_oracle_connection(self):
        """Oracle 연결 객체 반환 (Thick 모드 지원)"""
        try:
            import oracledb
        except ImportError:
            try:
                import cx_Oracle as oracledb
            except ImportError:
                raise models.UserError(
                    "Oracle 드라이버가 설치되지 않았습니다. "
                    "'pip install oracledb' 또는 'pip install cx_Oracle'을 실행하세요."
                )

        # Thick 모드 초기화 (한번만)
        if self.oracle_client_path and hasattr(oracledb, 'init_oracle_client'):
            try:
                oracledb.init_oracle_client(lib_dir=self.oracle_client_path)
            except oracledb.ProgrammingError:
                # 이미 초기화된 경우 무시
                pass
            except Exception as e:
                _logger.warning("Oracle Thick 모드 초기화 실패: %s", e)

        dsn = oracledb.makedsn(self.oracle_host, self.oracle_port, sid=self.oracle_sid)
        return oracledb.connect(
            user=self.oracle_user,
            password=self.oracle_password,
            dsn=dsn,
        )

    def action_test_oracle_connection(self):
        """Oracle 연결 테스트"""
        self.ensure_one()
        try:
            conn = self._get_oracle_connection()
            # 버전 확인
            cursor = conn.cursor()
            cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
            row = cursor.fetchone()
            version = row[0] if row else "알 수 없음"
            conn.close()
        except Exception as e:
            raise models.UserError(f"Oracle 연결 실패: {e}")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Oracle 연결 성공",
                "message": f"{self.oracle_host}:{self.oracle_port}/{self.oracle_sid}\n{version}",
                "type": "success",
            },
        }
