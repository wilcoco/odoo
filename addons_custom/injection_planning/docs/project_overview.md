# Project Overview

## 서비스 목적
자동차 부품(범퍼, 도어트림, 그릴 등) 사출 성형 공장의 **생산계획 자동화** 시스템.
Oracle ERP에서 완제품 수요를 받아 BOM 전개 → 사출기 스케줄링 → MO 생성까지의 전체 흐름을 자동화한다.

## 대상 사용자
- **생산계획 관리자** (`group_planning_manager`): 전체 설정, 계획 확정, MO 생성
- **생산계획 담당자** (`group_planning_user`): 수요 입력, 계획 실행, 분석 조회

## 핵심 기능
1. **수요 관리**: Oracle CSV 임포트 또는 수동 입력 (완제품 기준)
2. **BOM 전개**: 완제품 수요 → 사출 부품 소요량 자동 계산
3. **사출기 스케줄링**: 금형-사출기 조합, 교대근무, 금형교체 고려한 자동 스케줄링
4. **일별 분석**: 사출 부품별 소요량/생산량/재고/안전재고 추이 그래프
5. **MO 생성**: 확정된 계획 → Odoo 제조 오더(MO) 자동 생성
6. **샘플 데이터**: 테스트용 마스터/수요/계획 일괄 생성 위자드

## 기술 스택
- **Odoo 18.0 Community** (Railway 배포)
- **Python 3.11+**
- **PostgreSQL** (Railway 관리형)
- **GitHub** → Railway 자동 배포 (브랜치: 18.0)
- **Go 미들웨어** (별도 리포: DAT 파일 → Odoo REST API 연동)

## 프로젝트 URL
- Odoo: https://odoo-production-0437.up.railway.app
- Git (Odoo): https://github.com/wilcoco/odoo.git (18.0)
- Git (Go): https://github.com/wilcoco/midlle_odoo.git (main)

## 모듈 위치
```
addons_custom/injection_planning/
```

## 외부 연동
- **Oracle ERP** → CSV 추출 → 파일 업로드 위자드
- **Go 미들웨어** → 사출기(CC300) DAT 파일 폴링 → Odoo REST API
- **바코드 로봇** → Go 미들웨어 → 라벨 출력 (계획 중)
- **중량 로봇** → Go 미들웨어 → 시리얼 중량 업데이트 (계획 중)
