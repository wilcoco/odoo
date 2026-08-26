# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models


class EsconMainmenuProfile(models.Model):
    """사용자별 메인 메뉴 설정 (즐겨찾기·카테고리·앱 순서·표시 상태).

    config 는 JSON 텍스트 하나로 통째로 저장한다. 스키마는 클라이언트(OWL)가
    소유하며, 서버는 사용자당 1레코드 저장소 역할만 한다.
    """

    _name = "escon.mainmenu.profile"
    _description = "ESCON 메인메뉴 사용자 설정"

    user_id = fields.Many2one(
        "res.users", string="사용자", required=True, index=True, ondelete="cascade"
    )
    config = fields.Text(string="설정(JSON)")

    _sql_constraints = [
        ("user_uniq", "unique(user_id)", "사용자당 설정은 하나만 존재할 수 있습니다."),
    ]

    @api.model
    def get_my_config(self):
        """현재 사용자의 설정을 dict 로 반환 (없으면 False)."""
        rec = self.search([("user_id", "=", self.env.uid)], limit=1)
        if rec and rec.config:
            try:
                return json.loads(rec.config)
            except ValueError:
                return False
        return False

    @api.model
    def save_my_config(self, config):
        """현재 사용자의 설정을 저장한다."""
        value = json.dumps(config, ensure_ascii=False)
        rec = self.search([("user_id", "=", self.env.uid)], limit=1)
        if rec:
            rec.config = value
        else:
            self.create({"user_id": self.env.uid, "config": value})
        return True

    @api.model
    def reset_my_config(self):
        """현재 사용자의 설정을 삭제해 기본값으로 되돌린다."""
        self.search([("user_id", "=", self.env.uid)]).unlink()
        return True
