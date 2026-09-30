from . import models
from . import wizards
from . import controllers


def post_init_hook(env):
    """[R135 Q3] 새 설치에서만 교체 인식 방식을 기본으로 둔다. 업그레이드(기존 config)는 건드리지 않는다."""
    env["injection.planning.config"].sudo().search([]).write({"sequencing_mode": "setup_aware"})
