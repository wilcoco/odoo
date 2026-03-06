import json
import logging

from odoo import http, fields, _
from odoo.http import request
from werkzeug.exceptions import BadRequest

_logger = logging.getLogger(__name__)


class EngelInjectionAPI(http.Controller):
    """Go 미들웨어 연동 REST API (Euromap 63 → Odoo)"""

    # ─────────────────────────────────────────────
    # 헬퍼
    # ─────────────────────────────────────────────
    def _json_body(self):
        """JSON 요청 바디 파싱"""
        try:
            return json.loads(request.httprequest.data)
        except (json.JSONDecodeError, TypeError) as exc:
            raise BadRequest("Invalid JSON body: %s" % str(exc))

    def _error_response(self, message, status=400):
        return request.make_json_response(
            {"success": False, "error": message},
            status=status,
        )

    def _success_response(self, data=None, status=200):
        resp = {"success": True}
        if data is not None:
            resp["data"] = data
        return request.make_json_response(resp, status=status)

    # ─────────────────────────────────────────────
    # 제조 오더 (MO)
    # ─────────────────────────────────────────────
    @http.route(
        "/api/v1/injection/mo",
        auth="bearer", type="http", methods=["GET"],
        csrf=False, readonly=True,
    )
    def get_active_mos(self, **kwargs):
        """활성 사출 제조 오더 목록"""
        domain = [("state", "in", ("confirmed", "progress"))]

        if kwargs.get("product_id"):
            domain.append(("product_id", "=", int(kwargs["product_id"])))
        if kwargs.get("workcenter_id"):
            domain.append(
                ("workorder_ids.workcenter_id", "=", int(kwargs["workcenter_id"]))
            )

        mos = request.env["mrp.production"].search(
            domain, order="date_start",
        )
        data = []
        for mo in mos:
            data.append({
                "id": mo.id,
                "name": mo.name,
                "product_id": mo.product_id.id,
                "product_name": mo.product_id.name,
                "product_barcode": mo.product_id.barcode or "",
                "qty_to_produce": mo.product_qty,
                "qty_produced": mo.qty_produced,
                "car_model": mo.car_model_id.name if mo.car_model_id else "",
                "mold_id": mo.mold_id.id if mo.mold_id else None,
                "mold_name": mo.mold_id.name if mo.mold_id else "",
                "mold_cavity_count": mo.mold_id.cavity_count if mo.mold_id else 0,
                "state": mo.state,
                "date_start": (
                    fields.Datetime.to_string(mo.date_start)
                    if mo.date_start else ""
                ),
            })
        return self._success_response(data)

    @http.route(
        "/api/v1/injection/mo/<int:mo_id>",
        auth="bearer", type="http", methods=["GET"],
        csrf=False, readonly=True,
    )
    def get_mo_detail(self, mo_id, **kwargs):
        """제조 오더 상세 (BOM 포함)"""
        mo = request.env["mrp.production"].browse(mo_id)
        if not mo.exists():
            return self._error_response("MO not found", 404)

        bom_lines = []
        for move in mo.move_raw_ids:
            bom_lines.append({
                "product_id": move.product_id.id,
                "product_name": move.product_id.name,
                "qty_required": move.product_uom_qty,
                "qty_done": move.quantity if hasattr(move, "quantity") else 0,
            })

        data = {
            "id": mo.id,
            "name": mo.name,
            "product_id": mo.product_id.id,
            "product_name": mo.product_id.name,
            "product_barcode": mo.product_id.barcode or "",
            "qty_to_produce": mo.product_qty,
            "qty_produced": mo.qty_produced,
            "car_model": mo.car_model_id.name if mo.car_model_id else "",
            "mold_id": mo.mold_id.id if mo.mold_id else None,
            "mold_name": mo.mold_id.name if mo.mold_id else "",
            "mold_cavity_count": mo.mold_id.cavity_count if mo.mold_id else 0,
            "state": mo.state,
            "bom_lines": bom_lines,
            "injection_serial_count": mo.injection_serial_count,
            "injection_ok_count": mo.injection_ok_count,
            "injection_ng_count": mo.injection_ng_count,
            "injection_defect_rate": mo.injection_defect_rate,
        }
        return self._success_response(data)

    @http.route(
        "/api/v1/injection/mo/<int:mo_id>/progress",
        auth="bearer", type="http", methods=["PUT"],
        csrf=False,
    )
    def update_mo_progress(self, mo_id, **kwargs):
        """제조 오더 생산 진행률 업데이트"""
        mo = request.env["mrp.production"].browse(mo_id)
        if not mo.exists():
            return self._error_response("MO not found", 404)

        body = self._json_body()
        update_vals = {}
        if "qty_produced" in body:
            update_vals["qty_produced"] = float(body["qty_produced"])
        if update_vals:
            mo.sudo().write(update_vals)

        return self._success_response({
            "id": mo.id,
            "name": mo.name,
            "state": mo.state,
            "qty_produced": mo.qty_produced,
        })

    # ─────────────────────────────────────────────
    # 시리얼 레코드
    # ─────────────────────────────────────────────
    @http.route(
        "/api/v1/injection/serial",
        auth="bearer", type="http", methods=["POST"],
        csrf=False,
    )
    def create_serial(self, **kwargs):
        """시리얼 레코드 단건 생성"""
        body = self._json_body()
        if "product_id" not in body:
            return self._error_response("Missing required field: product_id")

        vals = self._prepare_serial_vals(body)
        try:
            serial = request.env["engel.injection.serial"].sudo().create(vals)
            return self._success_response(
                {"id": serial.id, "barcode": serial.barcode},
                status=201,
            )
        except Exception as exc:
            _logger.exception("Failed to create injection serial")
            return self._error_response(str(exc), 500)

    @http.route(
        "/api/v1/injection/serial/bulk",
        auth="bearer", type="http", methods=["POST"],
        csrf=False,
    )
    def create_serial_bulk(self, **kwargs):
        """시리얼 레코드 벌크 생성 (Go서버 버퍼 전송용)"""
        body = self._json_body()
        records = body.get("records", [])
        if not records:
            return self._error_response("No records provided")

        vals_list = []
        for rec in records:
            if "product_id" not in rec:
                return self._error_response(
                    "Missing product_id in one of the records"
                )
            vals_list.append(self._prepare_serial_vals(rec))

        try:
            serials = request.env["engel.injection.serial"].sudo().create(
                vals_list
            )
            data = [
                {"id": s.id, "barcode": s.barcode} for s in serials
            ]
            return self._success_response(data, status=201)
        except Exception as exc:
            _logger.exception("Failed to bulk create injection serials")
            return self._error_response(str(exc), 500)

    def _prepare_serial_vals(self, body):
        """API 바디 → ORM vals 변환"""
        vals = {
            "product_id": int(body["product_id"]),
        }
        # 선택적 필드 매핑 (int 타입)
        int_fields = [
            "production_id", "lot_id", "mold_id",
            "mold_cavity", "operator_id", "defect_type_id",
            "car_model_id",
        ]
        for field in int_fields:
            if field in body and body[field] is not None:
                vals[field] = int(body[field])

        # 선택적 필드 매핑 (문자열 타입)
        str_fields = [
            "serial_no", "shift", "qc_result",
        ]
        for field in str_fields:
            if field in body and body[field] is not None:
                vals[field] = body[field]

        # 선택적 필드 매핑 (float 타입)
        float_fields = [
            "weight", "cycle_time", "inject_pressure",
            "hold_pressure", "barrel_temp", "mold_temp", "cushion",
        ]
        for field in float_fields:
            if field in body and body[field] is not None:
                vals[field] = float(body[field])

        # 생산 시각
        if "produced_at" in body and body["produced_at"]:
            vals["produced_at"] = body["produced_at"]

        return vals

    # ─────────────────────────────────────────────
    # 시리얼 조회 / 업데이트 (로봇 연동)
    # ─────────────────────────────────────────────
    @http.route(
        "/api/v1/injection/serial/<int:serial_id>",
        auth="bearer", type="http", methods=["GET"],
        csrf=False, readonly=True,
    )
    def get_serial(self, serial_id, **kwargs):
        """시리얼 레코드 조회 (ID)"""
        serial = request.env["engel.injection.serial"].browse(serial_id)
        if not serial.exists():
            return self._error_response("Serial not found", 404)
        return self._success_response(self._serial_to_dict(serial))

    @http.route(
        "/api/v1/injection/serial/barcode/<string:barcode>",
        auth="bearer", type="http", methods=["GET"],
        csrf=False, readonly=True,
    )
    def get_serial_by_barcode(self, barcode, **kwargs):
        """시리얼 레코드 조회 (바코드)"""
        serial = request.env["engel.injection.serial"].search(
            [("barcode", "=", barcode)], limit=1,
        )
        if not serial:
            return self._error_response("Serial not found", 404)
        return self._success_response(self._serial_to_dict(serial))

    @http.route(
        "/api/v1/injection/serial/<int:serial_id>",
        auth="bearer", type="http", methods=["PUT"],
        csrf=False,
    )
    def update_serial(self, serial_id, **kwargs):
        """시리얼 레코드 업데이트 (중량로봇, 바코드로봇 등)"""
        serial = request.env["engel.injection.serial"].sudo().browse(serial_id)
        if not serial.exists():
            return self._error_response("Serial not found", 404)

        body = self._json_body()
        vals = {}

        # 업데이트 가능 필드 (float)
        float_fields = [
            "weight", "cycle_time", "inject_pressure",
            "hold_pressure", "barrel_temp", "mold_temp", "cushion",
        ]
        for field in float_fields:
            if field in body and body[field] is not None:
                vals[field] = float(body[field])

        # 업데이트 가능 필드 (str)
        str_fields = ["qc_result", "status", "serial_no"]
        for field in str_fields:
            if field in body and body[field] is not None:
                vals[field] = body[field]

        # 업데이트 가능 필드 (int)
        int_fields = ["defect_type_id", "operator_id"]
        for field in int_fields:
            if field in body and body[field] is not None:
                vals[field] = int(body[field])

        if vals:
            serial.write(vals)

        return self._success_response(self._serial_to_dict(serial))

    @http.route(
        "/api/v1/injection/serial/pending",
        auth="bearer", type="http", methods=["GET"],
        csrf=False, readonly=True,
    )
    def get_pending_serials(self, **kwargs):
        """바코드 출력 대기 중인 시리얼 목록 (status=produced)"""
        domain = [("status", "=", "produced")]

        if kwargs.get("production_id"):
            domain.append(("production_id", "=", int(kwargs["production_id"])))
        if kwargs.get("limit"):
            limit = int(kwargs["limit"])
        else:
            limit = 50

        serials = request.env["engel.injection.serial"].search(
            domain, order="produced_at asc", limit=limit,
        )
        data = [self._serial_to_dict(s) for s in serials]
        return self._success_response(data)

    def _serial_to_dict(self, serial):
        """시리얼 레코드 → dict 변환"""
        return {
            "id": serial.id,
            "barcode": serial.barcode,
            "serial_no": serial.serial_no or "",
            "product_id": serial.product_id.id,
            "product_name": serial.product_id.name,
            "production_id": serial.production_id.id if serial.production_id else None,
            "production_name": serial.production_id.name if serial.production_id else "",
            "lot_id": serial.lot_id.id if serial.lot_id else None,
            "mold_id": serial.mold_id.id if serial.mold_id else None,
            "car_model": serial.car_model_id.name if serial.car_model_id else "",
            "weight": serial.weight,
            "cycle_time": serial.cycle_time,
            "inject_pressure": serial.inject_pressure,
            "hold_pressure": serial.hold_pressure,
            "barrel_temp": serial.barrel_temp,
            "mold_temp": serial.mold_temp,
            "cushion": serial.cushion,
            "qc_result": serial.qc_result,
            "status": serial.status,
            "produced_at": fields.Datetime.to_string(serial.produced_at) if serial.produced_at else "",
        }

    # ─────────────────────────────────────────────
    # 불량 유형 마스터
    # ─────────────────────────────────────────────
    @http.route(
        "/api/v1/injection/defect-types",
        auth="bearer", type="http", methods=["GET"],
        csrf=False, readonly=True,
    )
    def get_defect_types(self, **kwargs):
        """불량 유형 마스터 목록"""
        defects = request.env["engel.defect.type"].search(
            [("active", "=", True)]
        )
        data = [
            {"id": d.id, "code": d.code, "name": d.name}
            for d in defects
        ]
        return self._success_response(data)

    # ─────────────────────────────────────────────
    # 설비 상태
    # ─────────────────────────────────────────────
    @http.route(
        "/api/v1/injection/machine-status",
        auth="bearer", type="http", methods=["POST"],
        csrf=False,
    )
    def update_machine_status(self, **kwargs):
        """설비 상태 업데이트 (upsert)"""
        body = self._json_body()
        machine_name = body.get("machine_name")
        if not machine_name:
            return self._error_response("machine_name is required")

        MachineStatus = request.env["engel.machine.status"].sudo()
        existing = MachineStatus.search(
            [("machine_name", "=", machine_name)], limit=1,
        )

        vals = {
            "machine_name": machine_name,
            "status": body.get("status", "idle"),
            "updated_at": fields.Datetime.now(),
        }

        # 선택적 필드
        if body.get("workcenter_id"):
            vals["workcenter_id"] = int(body["workcenter_id"])
        if body.get("current_mo_id"):
            vals["current_mo_id"] = int(body["current_mo_id"])
        if "last_shot_time" in body and body["last_shot_time"]:
            vals["last_shot_time"] = body["last_shot_time"]
        if "total_shots_today" in body:
            vals["total_shots_today"] = int(body["total_shots_today"])
        if "cycle_time_avg" in body:
            vals["cycle_time_avg"] = float(body["cycle_time_avg"])

        if existing:
            existing.write(vals)
            return self._success_response(
                {"id": existing.id, "action": "updated"}
            )
        else:
            rec = MachineStatus.create(vals)
            return self._success_response(
                {"id": rec.id, "action": "created"}, status=201,
            )
