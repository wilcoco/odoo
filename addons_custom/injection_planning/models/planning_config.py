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

    # ── 교대/가동 시간 ──
    day_shift_hours = fields.Float(
        string="주간 근무시간 (시간)", default=8.0,
        help="주간 교대 근무 시간 (예: 8시간, 10시간)",
    )
    night_shift_hours = fields.Float(
        string="야간 근무시간 (시간)", default=8.0,
        help="야간 교대 근무 시간 (예: 8시간, 10시간)",
    )
    day_shift_start = fields.Float(
        string="주간 시작 시각", default=8.0,
        help="주간 근무 시작 (예: 8.0 = 오전 8시, 7.5 = 오전 7시 30분)",
    )
    night_shift_start = fields.Float(
        string="야간 시작 시각", default=20.0,
        help="야간 근무 시작 (예: 20.0 = 오후 8시)",
    )

    # ── 안전재고 ──
    safety_stock_days = fields.Float(
        string="안전재고 (일)", default=3,
        help="안전재고 확보 일수. 각 날짜로부터 향후 N일간 실제 수요를 "
             "충당할 수 있는 재고 수준 유지. 당일 생산 부족 없음 최우선.",
    )

    # ── MO 분할 ──
    mo_split_mode = fields.Selection(
        [
            ("none", "분할 안함 (일별 단일 MO)"),
            ("shift", "교대별 분할 (주간/야간)"),
        ],
        string="MO 분할 방식",
        default="none",
        help="교대별 분할: 생산이 교대를 넘어가면 별도 MO 생성. "
             "실시간 재고 추적과 교대별 실적 관리에 유용.",
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
