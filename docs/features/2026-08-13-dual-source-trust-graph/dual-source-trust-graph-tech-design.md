# 개발방향: 이중 출처 관계 그래프와 엣지 신뢰 등급

> **다음 단계 안내**: 이 문서는 기술 설계서입니다 (아키텍처 / 컴포넌트 / 데이터 / 인터페이스 / 결정 / 위험 / 테스트 전략). `dual-source-trust-graph-requirements.md` (PRD) 를 기반으로 작성되고, 다음 단계 `dual-source-trust-graph-implementation-plan.md` (단계별 계획) 의 입력이 됩니다. 단계별 구현 task 는 여기 박지 마세요 — 그건 다음 산출물에 들어갑니다.

---

## 1. 아키텍처 개요

### 파이프라인 7단

각 단은 **독립 실행 가능**하고 **체크포인트로 재개**된다. 앞 단이 실패해도 뒤 단이 이미 만든 산출물은 살아남는다.

```
DART OpenAPI
   │
   ├─ corpCode.xml ───────────┐
   ├─ 기업개황(induty_code) ──┴──▶ [1] 대상 선정 ──▶ targets 원장(Postgres)
   │
   ├─ 공시목록(list.json) ───────▶ [2] 수집 ──▶ rcept 원장(Postgres) + 원문(파일)
   │
   ├─ DS002 정형 9종 ─────────┐
   ├─ DS004 지분공시 ─────────┴──▶ [3a] 정형 관계 파서 ─┐
   │                                                     │
   └─ 원문 XML(II.사업의 내용) ──▶ [3b] 본문 LLM 추출 ──┤
                                      (vLLM · 자체 컨테이너) │
                                                            ▼
                                            [3c] 엔티티 해소 (이름 → corp_code)
                                                    │
                                                    ├─ 해소 성공 ──────┐
                                                    └─ 실패 → 미해소 대기열
                                                       (신규 노드 생성 금지)
                                                                       ▼
                                                   [4] 그래프 적재 (Neo4j)
                                                            │
                                                            ▼
                                                   [5] 신뢰 판정
                                                    ├ 시점 스코프 분리
                                                    ├ 교차확인 (정형↔정형 / 본문↔본문)
                                                    ├ 모순 검출 A~D
                                                    └ evidence_weight 인자 부여
                                                            │
                                                            ▼
                                                   [6] 품질 측정
                                                    ├ 재현율 (자동)
                                                    └ 정밀도 (층화표본 → 수동 검수)
                                                            │
                                                            ▼
                                                   [7] 내보내기 (엣지 목록)
                                                    └ 차수 보존 셔플용 · 후속 문서 입력
```

### 저장소 분담

| 저장소 | 담당 | 이유 |
|---|---|---|
| **Postgres** (`5435`) | 원장·상태·검수 기록 | 순차 스캔·집계·트랜잭션이 필요한 것. 재수집 재개의 기준점 |
| **Neo4j** (`7474`/`7687`) | 관계 그래프 | 다홉 질의·GDS 알고리즘. Cypher가 곧 감사 쿼리 |
| **파일시스템** | 원문 XML/ZIP | 재파싱·재추출의 원천. DB에 넣을 이유 없음 |
| **vLLM** (`8003`) | 본문 관계 추출 | OpenAI 호환 엔드포인트 |

### GDS 투영은 반드시 두 벌

Leiden은 `UNDIRECTED` 를 요구하는데 층위 계산은 방향이 필요하다. 저장은 방향을 보존하고, **투영에서 갈라 쓴다.**

```
Neo4j 저장 (방향 O · 단일 진실)
   ├─ 투영 A  orientation: NATURAL    → 입·출차수 · 공급 깊이 · betweenness
   └─ 투영 B  orientation: UNDIRECTED → Leiden 군집 · modularity
```

본 문서는 **두 투영이 모두 가능한 적재 형태**까지 책임진다 (투영·알고리즘 실행은 후속 문서).

---

## 2. 영향 받는 컴포넌트/파일

신규 프로젝트이므로 전부 신규다. 기존 코드 수정은 **없다** — `docs-rag` 는 참고만 하고 컨테이너·코드를 공유하지 않는다 (D3).

```
dartweave/
├─ docker-compose.yml            neo4j · postgres · vllm (전부 자체)
├─ pyproject.toml                uv 관리
├─ .env.example                  DART_API_KEY 등
├─ src/dartweave/
│  ├─ config.py                  포트·경로·상수·스코프 규칙
│  ├─ dart/                      ← §4 외부 인터페이스
│  │  ├─ client.py               레이트리밋 · 재시도 · 상태코드 분기
│  │  ├─ corpcode.py             corpCode.xml → 원장
│  │  ├─ disclosure.py           공시목록 + 원문 ZIP
│  │  └─ structured.py           DS002 9종 · DS004
│  ├─ select/targets.py          [1] induty_code 필터 + 수동 보정
│  ├─ parse/
│  │  ├─ structured_rel.py       [3a] 정형 응답 → 관계 레코드
│  │  └─ document.py             원문 XML → 섹션 분해 (II. 사업의 내용)
│  ├─ extract/
│  │  ├─ prompt.py               관계 추출 프롬프트 (출력 스키마 고정)
│  │  └─ runner.py               [3b] vLLM 배치 호출 + 체크포인트
│  ├─ resolve/                   ← 품질 지표의 오염원. 명시적 단계로 분리
│  │  ├─ normalize.py            표기 정규화 ((주)·주식회사·영문명·공백)
│  │  ├─ resolver.py             [3c] 이름 → corp_code. 실패는 대기열로
│  │  └─ alias.py                별칭 사전 (수동 보정 반영)
│  ├─ graph/
│  │  ├─ schema.py               노드·엣지 타입 · 제약 · 인덱스
│  │  ├─ load.py                 [4] idempotent 적재 (MERGE)
│  │  └─ export.py               [7] 엣지 목록 내보내기
│  ├─ trust/
│  │  ├─ scope.py                시점 스코프 판정
│  │  ├─ crosscheck.py           [5] 교차확인 (정형↔정형 / 본문↔본문)
│  │  ├─ contradiction.py        모순 A~D 검출
│  │  └─ weight.py               evidence_weight 인자 부여 + 파생 계산
│  └─ quality/
│     ├─ recall.py               [6] 재현율 (자동)
│     ├─ sample.py               층화 표본 + 원문 위치 첨부
│     └─ precision.py            검수 판정 → 구간별 실측 정확도 표
├─ scripts/                      단계별 CLI 엔트리 (1~7)
└─ tests/
```

### 수용기준 ↔ 컴포넌트 매핑

| AC | 담당 |
|---|---|
| AC-1 대상 목록 + 선정 사유 | `select/targets.py` · Postgres `company` |
| AC-2 3개 사업연도 접수번호 + 실패 사유 | `dart/disclosure.py` · Postgres `disclosure` |
| AC-3 엣지 필수 속성 · `mention_count` 집계 기준 | `graph/schema.py` · `graph/load.py` · `trust/weight.py` |
| AC-4 재현율 자동 | `quality/recall.py` |
| AC-4b 층화 표본 + 원문 위치 | `quality/sample.py` |
| AC-4c 실측 정확도의 가중치 반영 | `quality/precision.py` → `trust/weight.py` |
| AC-5 지분 합계 규칙 위반 | `trust/contradiction.py` · Postgres `contradiction` |
| AC-6 시점차 / 불일치 분리 | `trust/scope.py` · Postgres `relation_change` (시점차 적립) |
| AC-7 공급 엣지 양방향 판정 | `trust/crosscheck.py` |
| AC-8 `evidence_weight` + 분포 요약 | `trust/weight.py` |
| AC-9 방향 보존 + 내보내기(셔플·CPM·대체) | `graph/schema.py` · `graph/export.py` |
| AC-10 엔티티 해소율 + 미해소 대기열 | `resolve/*` · Postgres `entity_alias` · `unresolved_mention` |
| AC-11 품질 5차원 산출 | `quality/*` · `trust/contradiction.py` |

---

## 3. 데이터 모델/스키마

### Postgres — 원장·상태·검수

| 테이블 | 핵심 컬럼 | 역할 |
|---|---|---|
| `company` | `corp_code`(PK) · `corp_name` · `stock_code` · `induty_code` · `corp_cls` · `selected` · `select_reason` | AC-1. **선정 사유를 컬럼으로 강제** — 수동 보정이 기록 없이 일어나는 걸 막는다 |
| `disclosure` | `rcept_no`(PK) · `corp_code` · `report_nm` · `rcept_dt` · `fiscal_year` · `as_of` · `fetch_status` · `fail_reason` | AC-2. 실패를 침묵으로 넘기지 않기 위해 `fail_reason` 필수 |
| `extraction_run` | `run_id` · `model` · `prompt_version` · `started_at` | 어떤 모델·프롬프트로 뽑은 엣지인지 추적. 모델 교체 시 실측 정확도 표 무효화 판단 근거 |
| `precision_sample` | `edge_key` · `rcept_no` · `snippet` · `confidence` · `verdict` · `verified_at` | AC-4b. 검수 가능한 형태로 원문 구절 동봉 |
| `precision_table` | `conf_bucket` · `n_sample` · `n_correct` · `observed_precision` | AC-4c. **이 표가 가중치의 근거** |
| `entity_alias` | `surface_form`(PK) · `corp_code` · `source`(`auto`\|`manual`) · `added_at` | AC-10. 해소된 표기를 누적. 수동 보정이 다음 실행에 자동 반영됨 |
| `unresolved_mention` | `surface_form` · `rcept_no` · `snippet` · `occurrences` · `status` | AC-10. **미해소는 여기로만 간다.** 신규 노드 생성 경로 없음 |
| `relation_change` | `edge_key` · `from_fiscal_year` · `to_fiscal_year` · `from_value` · `to_value` · `from_rcept_no` · `to_rcept_no` | **요구사항 결정 5** — 시점차로 분류된 건을 버리지 않고 적립하는 곳. 후속 "지분 변동 타임라인"의 원료 |
| `contradiction` | `grade`(A\|B\|C\|D) · `edge_key` · `detail`(JSON) · `detected_at` · `verdict` · `verdict_by` | **요구사항 결정 6** — 모순 검출 결과의 영구 기록. `verdict` 는 후속 감사 워크벤치의 판정(정형채택/본문채택/보류)이 쓰는 자리 |

### Neo4j — 그래프

**노드**: `(:Company {corp_code, name})` · `(:Person {name, ...})` · `(:Auditor {name})` · `(:Product {name})`

**엣지 타입**: `MAJOR_SHAREHOLDER_OF` · `INVESTS_IN` · `HOLDS_5PCT` · `EXECUTIVE_OF` · `AUDITED_BY` · `SUPPLIES_TO` · `PRODUCES`

**모든 엣지 필수 속성** (AC-3):

| 속성 | 의미 |
|---|---|
| `rcept_no` | 출처 접수번호 |
| `as_of` | **기준일** — 시점 스코프 판정의 근거 (AC-6) |
| `fiscal_year` | 사업연도 |
| `source` | `structured` \| `text` |
| `mention_count` | **서로 다른 출처 주체** 기준 집계 (AC-3) |

**조건부 속성**: `confidence`(본문만·원본 보관용) · `snippet_ref`(본문만) · `cross_confirmed`·`counterpart_rcept_no`(교차확인 시) · `share_pct`(정량)

> ⚠️ **`evidence_weight` 는 저장하지 않는다** (D5). 인자만 영구 저장하고, GDS 투영 직전에 계산해서 `mutate` 한다.

**제약·인덱스**
- `Company.corp_code` UNIQUE
- `rcept_no` INDEX (감사 쿼리가 출처로 역추적)
- 엣지 중복 방지 키: `(시작, 끝, 타입, fiscal_year, source)` — 재적재가 중복을 만들지 않도록 `MERGE` 의 매칭 키로 사용

### `mention_count` 집계 규칙 (요구사항 결정 3)

```
집계 키 = (엣지 정체성, 출처 주체)
  출처 주체 = (보고 회사 corp_code, 보고서 종류)

같은 회사 · 같은 보고서 종류 · 3개 사업연도  → 1
A사 보고서 + B사 보고서                      → 2
사업보고서 + 주요사항보고서                  → 2
```

**연차 반복이 2 이상으로 세어지면 AC-3 실패다.** 단위 테스트로 고정한다 (§7).

---

## 4. 외부 인터페이스

**소비만 한다. 노출 API 없음** — 아래층은 배치 파이프라인이다.

### DART OpenAPI

| 엔드포인트 | 용도 | 단계 |
|---|---|---|
| `GET /api/corpCode.xml` | 전체 기업 고유번호 (ZIP) | [1] |
| `GET /api/company.json` | 기업개황 — `induty_code` 확보 | [1] |
| `GET /api/list.json` | 공시목록 | [2] |
| `GET /api/document.xml` | 원문 (ZIP) | [2] |
| DS002 9종 · DS004 | 정형 관계 | [3a] |

**상태코드 분기** (`dart/client.py` 단일 지점에서 처리):

| 코드 | 의미 | 처리 |
|---|---|---|
| `000` | 정상 | 진행 |
| `013` | 데이터 없음 | **정상 처리** — 빈 결과로 기록. 실패 아님 |
| `020` | 한도 초과 | 백오프 후 재시도 |
| `010` | 잘못된 키 | **즉시 중단** — 재시도 무의미, 사용자 개입 필요 |

### vLLM

OpenAI 호환 `POST /v1/chat/completions` (`localhost:8003`). 출력은 **고정 스키마 JSON** 으로 강제한다 — 자유 서술을 파싱하면 추출 품질과 파싱 버그가 뒤섞여 재현율 측정이 오염된다.

---

## 5. 핵심 결정 + 대안 비교

### D1 — 그래프 저장소: **Neo4j + GDS**

| 대안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **Neo4j + GDS** | Leiden·betweenness·modularity 내장. `gds.leiden.stats` 가 `modularity` 직접 반환 | 컨테이너 추가 · JVM 메모리 · GDS Community 동시성 제한 | ✅ **채택** |
| Postgres + igraph | 인프라 최소 · 커스텀 자유 | Cypher 없음 · 그래프 질의 직접 구현 | ✗ |
| Neo4j (GDS 없이) + igraph | 라이선스 불확실성 회피 | 데이터 왕복 비용 | ✗ (D7의 fallback으로 유지) |

**근거**: 검증 ③의 핵심 지표 `modularity` 를 직접 구현하면 그 구현 자체가 버그 원천이 된다. 검증 도구가 검증 대상보다 못 미더우면 안 된다.

### D2 — 추출 모델: **로컬 vLLM**

| 대안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **로컬 vLLM** | 반복 재추출 비용 0 | GPU 8GB 제약 · 속도 | ✅ **채택** |
| API 모델 | 품질·속도 | 재추출마다 비용 | ✗ |
| 하이브리드 | 균형 | 실측 정확도 표가 **두 벌** 필요 → 복잡도 증가 | ✗ |

**근거**: 요구사항 결정 7이 재현율에 따른 **재작업 루프**를 명시한다. 반복이 전제인 작업에서 호출당 비용은 실험 횟수를 직접 깎는다. 또한 하이브리드는 모델별로 실측 정확도 표를 따로 관리해야 해서 AC-4c가 복잡해진다.

### D3 — 인프라: **완전 별도 compose**

`docs-rag` 컨테이너를 공유하지 않는다. 포트만 겹치지 않게 배정한다.

**근거**: 공유하면 `docs-rag` 변경이 dartweave를 깨뜨린다. 두 프로젝트의 수명주기가 다르다.

### D4 — 오케스트레이션: **단순 스크립트 + 체크포인트**

| 대안 | 판정 |
|---|---|
| **스크립트 + Postgres 체크포인트** | ✅ 배치 성격 · 재개는 원장 조회로 충분 |
| Celery + RabbitMQ | ✗ 운영 복잡도만 추가. 실시간 큐가 필요 없다 |

### D5 — `evidence_weight`: **인자만 저장, 파생 계산**

| 대안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **인자 저장 + 파생** | 실측 정확도 표만 갈아끼우면 전체가 갱신됨 | 투영마다 계산 | ✅ **채택** |
| 적재 시 고정값 저장 | 조회 빠름 | 표가 갱신될 때마다 **전수 UPDATE** | ✗ |
| 질의 시 매번 계산 | 항상 최신 | GDS가 실제 속성을 요구 | ✗ |

**근거**: 정밀도 검수는 **한 번에 끝나지 않는다.** 표본을 더 검수하면 `precision_table` 이 좋아지고, 그때마다 모든 엣지 가중치가 바뀐다. 값을 박아두면 이게 전수 마이그레이션이 된다.

### D6 — 투영 두 벌: **NATURAL + UNDIRECTED**

선택이 아니라 **제약의 귀결**이다. Leiden이 `UNDIRECTED` 를 요구하고 층위 계산은 방향이 필요하다. 단일 진실은 Neo4j 저장이고, 투영에서만 갈린다.

### D7 — 라이선스는 해소됐고, 남은 제약은 **CPM 미지원**이다

**라이선스 (확정)** — GDS 2.13 공식 문서:

> *"The Community Edition is open source and **includes all algorithms** but has limitations on catalog operations, concurrency (4 CPU cores), and model catalog capacity (3 models)."* — [`enterprise-features.adoc`](https://github.com/neo4j/graph-data-science/blob/2.13/doc/modules/ROOT/partials/introduction/enterprise-features.adoc)
>
> *"These limits are determined by **the GDS license, not the Neo4j database edition**."* — [`System-requirements.adoc`](https://github.com/neo4j/graph-data-science/blob/2.13/doc/modules/ROOT/pages/installation/System-requirements.adoc)

→ Leiden·Betweenness 모두 Community에 포함. 4코어 제한은 이 규모에서 무의미. **Neo4j Community + GDS Community 조합 성립.**

설치는 Docker 환경변수 한 줄이다:
```yaml
neo4j:
  environment:
    NEO4J_PLUGINS: '["graph-data-science"]'
```
설치 확인은 `RETURN gds.version()`. **Neo4j ↔ GDS 버전 호환 매트릭스를 이미지 태그 고정 전에 확인한다.**

**남은 제약 (신규 발견) — GDS Leiden은 모듈러리티 전용이다**

> `gamma` — *"a Float with a default value of 1.0, **used for calculating modularity**"*
> `theta` — *"controls the randomness when breaking a community into smaller ones"*
> Leiden — *"aims to identify disjoint communities by **maximizing a modularity score**"*
> — [`leiden.adoc`](https://github.com/neo4j/graph-data-science/blob/2.13/doc/modules/ROOT/pages/algorithms/leiden.adoc) (2.13)

**목적함수 선택지가 없다.** CPM(Constant Potts Model) 옵션이 없으므로 **모듈러리티 최적화의 해상도 한계**를 GDS 안에서는 피할 수 없다 — 네트워크 전체 크기에 의존하는 규모보다 작은 군집은 원리적으로 식별되지 않는다 (Fortunato & Barthélemy, PNAS 104(1):36–41, 2007).

**우리한테 이게 왜 치명적인가**: 후속 문서의 하이라이트가 *"소재 군집 의존도"* 인데, **소재 기업이 소수면 실제로 독립 군집이어도 인접 군집에 흡수된다.** 하이라이트가 통째로 안 보일 수 있다.

**결론 — igraph 병행은 fallback이 아니라 정규 경로다.** 따라서 AC-9의 엣지 내보내기는 **세 목적을 겸한다**:

| # | 목적 | 왜 GDS로 안 되나 |
|---|---|---|
| 1 | 차수 보존 귀무모형 (검증 ③) | GDS에 차수 보존 셔플 없음 |
| 2 | **CPM 목적함수 재실행** | GDS Leiden은 모듈러리티 전용 |
| 3 | GDS 장애 시 대체 경로 | — |

### D9 — 엔티티 해소: **명시적 단계 + 침묵 생성 금지**

| 대안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **명시 단계 + 미해소 대기열** | 오염 경로 차단 · 해소율이 지표로 노출 | 대기열 처리 비용 | ✅ **채택** |
| 미해소 시 신규 노드 자동 생성 | 파이프라인이 안 멈춤 | **그래프가 조용히 오염됨.** 같은 회사가 쪼개져 교차확인 실패 → 재현율 왜곡 | ✗ |
| 이름 문자열을 그대로 노드 키로 | 구현 단순 | 표기 흔들림이 전부 별개 노드 | ✗ |

**근거**: 다른 그래프를 정답으로 쓸 때 오류는 두 군데서 들어온다 — 정답 그래프 자체의 오류, 그리고 **두 그래프를 연결하는 과정의 오류** (Paulheim, *Knowledge graph refinement*, Semantic Web 8(3), 2016). 우리 경우 후자가 곧 엔티티 해소다.

해소가 틀리면 피해가 품질 지표로 직행한다:
```
같은 회사가 두 노드로 쪼개짐
  → 교차확인 실패 → 실제 T1이 T3으로 강등
  → 재현율이 실제보다 낮게 측정
  → "추출이 나쁘다"는 잘못된 결론 → 엉뚱한 재작업
```

수동 보정은 `entity_alias` 에 누적되어 **다음 실행에 자동 반영**된다 (사람 손이 데이터가 되는 구조 — 정밀도 검수와 같은 패턴).

### D8 — 포트 배정 (충돌 확인 완료)

| 서비스 | 포트 | 비고 |
|---|---|---|
| Neo4j HTTP / Bolt | `7474` / `7687` | 미사용 확인 |
| Postgres | `5435` | 5433·5434·5436 점유 중 → 5435 |
| vLLM | `8003` | 8002 점유 중 |

---

## 6. 위험 / 사이드이펙트 (preliminary)

| 위험 | 카테고리 | 대응 |
|---|---|---|
| **`DART_API_KEY` 부재** | **blocking** | 사용자 발급 필요. 그 전까지 fixture 기반으로 전 단계 개발·테스트 가능하게 설계 |
| **엔티티 해소 실패 → 품질 지표 오염** | **breaking** | D9. 미해소 대기열 + 해소율 지표. 신규 노드 침묵 생성 경로를 코드에 두지 않음 |
| **CPM 미지원 → 작은 군집 누락** | **breaking** | D7. igraph CPM 병행이 정규 경로. AC-9 내보내기가 전제 |
| GDS ↔ Neo4j 버전 비호환 | breaking | 이미지 태그 고정 전 호환 매트릭스 확인 · `gds.version()` 로 사후 검증 |
| `mention_count` 오집계 → 가중치 부풀림 | breaking | 집계 키를 출처 주체로 고정 + 단위 테스트 (§7) |
| **재현율을 상한으로 오해** | side-effect | 정답(정형 API)도 완전하지 않음을 산출물에 병기. §7 참조 |
| 원문 XML 서식 변동 → 섹션 파서 실패 | breaking | 실패를 침묵시키지 않고 카운트·로그. 누락률을 지표로 노출 |
| 재적재 시 엣지 중복 | side-effect | `MERGE` + 복합 매칭 키 |
| GPU 경합 (`docs-rag` vLLM 동시 기동) | side-effect | 순차 기동. 현재 GPU 여유 7.5GB 확인됨 |
| API 한도(`020`) 초과 | side-effect | 백오프 + 원장 기반 재개 |
| 정형 API 응답 스키마 변경 | breaking | 계약 테스트 fixture (§7) |
| 층화 표본 편향 → 실측 정확도 왜곡 | side-effect | confidence 구간별 균등 표본 + 표본수 명시 |

---

## 7. 테스트 전략

**핵심 원칙: 실 API 없이 전 파이프라인이 돌아야 한다.** `DART_API_KEY` 가 블로커인 상태에서 개발이 멈추면 안 된다.

| 층위 | 대상 | 비고 |
|---|---|---|
| **계약** | DART 응답 스키마 fixture (DS002 9종 · DS004 · list · company) | 실 API 없이 [1]~[3a] 전체 구동 |
| **단위** | `scope.py` 시점 판정 · `weight.py` 파생 계산 · `contradiction.py` 규칙 A | 경계값 중심 |
| **단위(중요)** | **`mention_count` 자기인용 케이스** | 같은 회사 3개 연도 → **반드시 1**. AC-3 직결 |
| **단위** | `client.py` 상태코드 분기 (`000`/`013`/`020`/`010`) | `013`이 실패로 처리되면 안 됨 |
| **통합** | 소량 fixture로 수집→적재→교차확인 e2e | 그래프가 실제로 서는지 |
| **멱등성** | 같은 입력 2회 적재 → 엣지 수 불변 | 재적재 중복 방지 |
| **품질 회귀** | 재현율 자동 산출을 회귀 지표로 고정 | 프롬프트 수정이 품질을 떨어뜨리면 즉시 감지 |
| **골든** | 알려진 관계 소수를 골든으로 고정 | 적재 회귀 검출 |

`precision` 은 수동 검수가 개입하므로 자동 테스트 대상이 아니다 — 대신 **표본 추출과 표 산출 로직**을 단위 테스트한다.

### 품질 지표는 5개 차원으로 나눠 산출한다 (AC-11)

지식그래프 품질 차원은 이미 정리된 체계가 있으므로 새로 정의하지 않고 채택한다.

| 차원 | 우리 맥락의 질문 | 측정 |
|---|---|---|
| **Accuracy** | LLM이 뽑은 관계가 사실인가 | 재현율(자동) + 정밀도(표본 수동 검수) |
| **Completeness** | 원문에 있는 관계를 다 뽑았나 | 재현율 + **고립 노드 비율** |
| **Consistency** | 서로 모순되는 관계가 있나 | 규칙 위반 건수 (모순 등급 A) |
| **Timeliness** | 언제 시점 기준의 관계인가 | 시점 스코프 분포 · 미상 건수 |
| **Redundancy** | 같은 관계가 중복 저장됐나 | 정규화 후 중복 엣지 비율 |

여기에 본 설계가 하나를 더 붙인다:

| **해소율** | 본문 기업명이 `corp_code`로 매핑됐나 | 해소 건수 / 전체 언급 건수 (AC-10) |
|---|---|---|

**해소율이 낮으면 나머지 지표를 읽으면 안 된다.** 해소가 깨진 상태의 재현율은 추출 품질이 아니라 매핑 실패를 측정한 값이다. 지표 보고 순서를 **해소율 → 나머지**로 고정한다.

### ⚠️ 재현율은 상한이 아니라 근사치다 — 산출물에 병기한다

정답으로 쓰는 정형 API도 완전하지 않고, 정형↔본문을 같은 노드로 병합하는 과정에서도 오류가 들어온다. 따라서:

- 자동 재현율은 **"근사치"** 로 표기한다. *"재현율 상한"* 같은 표현을 쓰지 않는다
- **정밀도는 반드시 사람이 표본 검수**한다 (자동 대체 불가)
- 두 값을 **항상 함께** 보고한다 — 한쪽만 있으면 오독된다

판정 구간은 다음과 같이 두되, **이건 문헌 기준이 아니라 우리가 정한 실용 기준**임을 문서에 남긴다:

| 재현율 | 판정 |
|---|---|
| 높음 | 구조 분석(후속 문서)으로 진행 |
| 중간 | 진행하되 결과에 신뢰 등급 병기 필수 |
| 낮음 | 추출 개선이 우선 — 구조 분석은 이르다 |

---

## 변경이력

<!-- change-history skill auto-appends entries here, oldest first -->

### [2026-08-13 12:24] [개발방향-수정]
- **id**: CH-20260813-004
- **이유**: 신규 기술 설계 (최초 생성). 작성 중 확정된 외부 사실 2건과 자체 발견 1건이 설계를 바꿈 — (a) **GDS Community에 모든 알고리즘 포함** 확인으로 라이선스 불확실성 해소, (b) **GDS Leiden이 모듈러리티 전용(CPM 미지원)** 확인 → 해상도 한계를 GDS 내부에서 회피 불가 → igraph 병행이 fallback이 아니라 정규 경로로 승격, (c) **엔티티 해소 단계 누락** 자체 발견 → 상류(요구사항)까지 cascade
- **무엇이**: `dual-source-trust-graph-tech-design.md` 전체 — §1 아키텍처(7단 파이프라인 + 투영 두 벌) / §2 컴포넌트 22개 + AC 매핑표 / §3 데이터 모델(Postgres 8테이블 + Neo4j 노드·엣지 스키마) / §4 외부 인터페이스(DART 상태코드 분기 · vLLM) / §5 핵심 결정 D1~D9 + 대안 비교 / §6 위험 9건 / §7 테스트 전략 + 품질 5차원
- **영향범위**: 없음 (최초 생성, 신규 프로젝트라 기존 코드 수정 0건). 다만 상류 `dual-source-trust-graph-requirements.md` 에 역방향 변경을 유발함 — CH-20260813-003 참조
- **검증 결과**: `verifying-spec` 4축 — Mapped 22건 / **Gaps 2건 (본 엔트리에서 해소)** / Conflicts 0건 / 위험 `blocking 1 · breaking 6 · side-effect 5 · race 0` / 테스트 커버리지 0 (미구현)
  - Gap ①: 요구사항 결정 5의 *"시점차를 버리지 않고 적립"* 의 **저장 위치 미정의** → `relation_change` 테이블 신설
  - Gap ②: 모순 검출 결과의 **영구 기록 부재** (건수 출력만으로는 후속 감사 워크벤치가 소비 불가) → `contradiction` 테이블 신설 (`verdict` 컬럼이 후속 판정 자리)
  - ⚠️ `race 0` 은 **[2] 수집이 단일 프로세스라는 전제**에 의존. 구현계획에서 병렬화 도입 시 원장 write 경합 재평가 필요
- **연관 항목**: CH-20260813-001, CH-20260813-003
