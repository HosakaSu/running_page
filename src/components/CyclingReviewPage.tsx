import { useEffect, useMemo, useState } from 'react';

type ReviewDecision = 'cycling' | 'keep_running' | 'unsure';
type DecisionFilter = 'all' | 'unreviewed' | ReviewDecision;
type Confidence = 'confirmed' | 'high' | 'medium' | 'review';

interface ReviewRecord {
  run_id: number;
  confidence: Confidence;
  route_group: string;
  direction: 'home_to_work' | 'work_to_home';
  start_date_local: string;
  weekday: string;
  distance_km: string;
  moving_time: string;
  average_speed_mps: string;
  average_speed_kmh: string;
  endpoint_error_m: string;
}

interface ReviewPayload {
  generated_at: string;
  records: ReviewRecord[];
}

type Decisions = Record<string, ReviewDecision>;
type SyncState = 'idle' | 'saving' | 'saved' | 'error';

const STORAGE_KEY = 'running-page-cycling-review-v1';
const PAGE_SIZE = 50;

const decisionOptions: {
  value: ReviewDecision;
  label: string;
  icon: string;
  selectedClass: string;
}[] = [
  {
    value: 'cycling',
    label: '确认骑行',
    icon: '🚲',
    selectedClass: 'border-blue-500 bg-blue-500 text-white',
  },
  {
    value: 'keep_running',
    label: '保留跑步',
    icon: '🏃',
    selectedClass: 'border-orange-500 bg-orange-500 text-white',
  },
  {
    value: 'unsure',
    label: '暂不确定',
    icon: '？',
    selectedClass: 'border-slate-500 bg-slate-500 text-white',
  },
];

const confidenceLabels: Record<Confidence, string> = {
  confirmed: '已确认',
  high: '高疑似',
  medium: '中等疑似',
  review: '边界复核',
};

function loadStoredDecisions(): Decisions {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? (JSON.parse(stored) as Decisions) : {};
  } catch {
    return {};
  }
}

function saveDecisions(decisions: Decisions) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions));
}

function ReviewChoice({
  option,
  selected,
  onClick,
}: {
  option: (typeof decisionOptions)[number];
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`flex min-h-10 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
        selected
          ? option.selectedClass
          : 'border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-muted)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)]'
      }`}
    >
      <span aria-hidden="true">{selected ? '✓' : option.icon}</span>
      {option.label}
    </button>
  );
}

export function CyclingReviewPage() {
  const [payload, setPayload] = useState<ReviewPayload | null>(null);
  const [loadError, setLoadError] = useState('');
  const [decisions, setDecisions] = useState<Decisions>(loadStoredDecisions);
  const [syncState, setSyncState] = useState<SyncState>('idle');
  const [decisionFilter, setDecisionFilter] =
    useState<DecisionFilter>('unreviewed');
  const [yearFilter, setYearFilter] = useState('all');
  const [confidenceFilter, setConfidenceFilter] = useState<'all' | Confidence>(
    'all'
  );
  const [page, setPage] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const dataRequest = fetch(
      `${import.meta.env.BASE_URL}cycling-review.json`,
      { signal: controller.signal }
    ).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<ReviewPayload>;
    });
    const savedRequest = fetch(
      `${import.meta.env.BASE_URL}api/cycling-review-decisions`,
      { signal: controller.signal }
    )
      .then((response) =>
        response.ok
          ? (response.json() as Promise<{ decisions?: Decisions }>)
          : { decisions: {} }
      )
      .catch(() => ({ decisions: {} }));

    Promise.all([dataRequest, savedRequest])
      .then(([data, saved]) => {
        const defaults = Object.fromEntries(
          data.records
            .filter((record) => record.confidence === 'confirmed')
            .map((record) => [String(record.run_id), 'cycling'])
        ) as Decisions;
        setDecisions((current) => {
          const merged = { ...defaults, ...saved.decisions, ...current };
          saveDecisions(merged);
          return merged;
        });
        setPayload(data);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError')
          return;
        setLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!payload) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setSyncState('saving');
      fetch(`${import.meta.env.BASE_URL}api/cycling-review-decisions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions }),
        signal: controller.signal,
      })
        .then((response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          setSyncState('saved');
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === 'AbortError')
            return;
          setSyncState('error');
        });
    }, 400);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [decisions, payload]);

  const records = useMemo(() => payload?.records ?? [], [payload]);
  const years = useMemo(
    () => [
      ...new Set(records.map((record) => record.start_date_local.slice(0, 4))),
    ],
    [records]
  );
  const counts = useMemo(() => {
    const result = {
      cycling: 0,
      keep_running: 0,
      unsure: 0,
      unreviewed: 0,
    };
    records.forEach((record) => {
      const decision = decisions[String(record.run_id)];
      if (decision) result[decision] += 1;
      else result.unreviewed += 1;
    });
    return result;
  }, [records, decisions]);

  const filtered = useMemo(
    () =>
      records.filter((record) => {
        const decision = decisions[String(record.run_id)];
        if (decisionFilter === 'unreviewed' && decision) return false;
        if (
          decisionFilter !== 'all' &&
          decisionFilter !== 'unreviewed' &&
          decision !== decisionFilter
        )
          return false;
        if (
          yearFilter !== 'all' &&
          !record.start_date_local.startsWith(yearFilter)
        )
          return false;
        return (
          confidenceFilter === 'all' || record.confidence === confidenceFilter
        );
      }),
    [records, decisions, decisionFilter, yearFilter, confidenceFilter]
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const visible = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE
  );
  const reviewed = records.length - counts.unreviewed;
  const progress = records.length ? (reviewed / records.length) * 100 : 0;

  const setDecision = (runId: number, decision: ReviewDecision) => {
    setDecisions((current) => {
      const key = String(runId);
      const next = { ...current };
      if (next[key] === decision) delete next[key];
      else next[key] = decision;
      saveDecisions(next);
      return next;
    });
  };

  const exportDecisions = () => {
    const reviewedRecords = records
      .filter((record) => decisions[String(record.run_id)])
      .map((record) => ({
        run_id: record.run_id,
        start_date_local: record.start_date_local,
        decision: decisions[String(record.run_id)],
      }));
    const result = {
      version: 1,
      exported_at: new Date().toISOString(),
      total_candidates: records.length,
      reviewed: reviewedRecords.length,
      decisions: reviewedRecords,
    };
    const url = URL.createObjectURL(
      new Blob([`${JSON.stringify(result, null, 2)}\n`], {
        type: 'application/json',
      })
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = `cycling-review-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loadError) {
    return (
      <main className="mx-auto max-w-[1400px] px-6 py-10">
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-6">
          <h1 className="text-lg font-bold">无法加载骑行复核数据</h1>
          <p className="mt-2 text-sm text-[var(--color-muted)]">
            请重新运行审核数据生成脚本。错误：{loadError}
          </p>
        </div>
      </main>
    );
  }

  if (!payload) {
    return (
      <main className="mx-auto max-w-[1400px] px-6 py-20 text-center text-sm text-[var(--color-muted)]">
        正在加载骑行复核记录…
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
      <section className="mb-6 overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="p-5 sm:p-6">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
            <div>
              <p className="mb-1 text-xs font-semibold tracking-[0.18em] text-blue-500 uppercase">
                Apple Health 数据清理
              </p>
              <h1 className="text-2xl font-bold sm:text-3xl">骑行记录复核</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--color-muted)]">
                请根据开始时间、耗时和平均速度判断。选择会自动保存在当前浏览器，不会立即修改跑步数据库。
              </p>
            </div>
            <div className="flex flex-col items-stretch gap-2 sm:items-end">
              <button
                type="button"
                onClick={exportDecisions}
                disabled={reviewed === 0}
                className="rounded-lg bg-[var(--color-accent)] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                下载审核结果
              </button>
              <span
                className={`text-xs ${
                  syncState === 'error'
                    ? 'text-red-500'
                    : 'text-[var(--color-muted)]'
                }`}
              >
                {syncState === 'saving' && '正在同步到项目…'}
                {syncState === 'saved' && '✓ 已同步到远程项目'}
                {syncState === 'error' && '同步失败，浏览器内仍已保存'}
                {syncState === 'idle' && '选择会自动保存'}
              </span>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['待判断', counts.unreviewed, 'text-[var(--color-text)]'],
              ['确认骑行', counts.cycling, 'text-blue-500'],
              ['保留跑步', counts.keep_running, 'text-orange-500'],
              ['暂不确定', counts.unsure, 'text-slate-500'],
            ].map(([label, value, color]) => (
              <div
                key={String(label)}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] p-3 sm:p-4"
              >
                <div className={`text-2xl font-bold ${color}`}>{value}</div>
                <div className="mt-1 text-xs text-[var(--color-muted)]">
                  {label}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-5">
            <div className="mb-2 flex justify-between text-xs text-[var(--color-muted)]">
              <span>
                已审核 {reviewed} / {records.length}
              </span>
              <span>{progress.toFixed(1)}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-[var(--color-border)]">
              <div
                className="h-full rounded-full bg-[var(--color-accent)] transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="flex flex-col gap-3 border-b border-[var(--color-border)] p-4 sm:flex-row sm:flex-wrap sm:items-center">
          <select
            value={decisionFilter}
            onChange={(event) => {
              setDecisionFilter(event.target.value as DecisionFilter);
              setPage(0);
            }}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm"
          >
            <option value="unreviewed">只看待判断</option>
            <option value="all">全部状态</option>
            <option value="cycling">确认骑行</option>
            <option value="keep_running">保留跑步</option>
            <option value="unsure">暂不确定</option>
          </select>
          <select
            value={yearFilter}
            onChange={(event) => {
              setYearFilter(event.target.value);
              setPage(0);
            }}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm"
          >
            <option value="all">全部年份</option>
            {years.map((year) => (
              <option key={year} value={year}>
                {year} 年
              </option>
            ))}
          </select>
          <select
            value={confidenceFilter}
            onChange={(event) => {
              setConfidenceFilter(event.target.value as 'all' | Confidence);
              setPage(0);
            }}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm"
          >
            <option value="all">全部疑似程度</option>
            <option value="confirmed">已确认</option>
            <option value="high">高疑似</option>
            <option value="medium">中等疑似</option>
            <option value="review">边界复核</option>
          </select>
          <span className="text-sm text-[var(--color-muted)] sm:ml-auto">
            当前显示 {filtered.length} 条
          </span>
        </div>

        <div className="divide-y divide-[var(--color-border)]">
          {visible.map((record) => {
            const decision = decisions[String(record.run_id)];
            const [date, time] = record.start_date_local.split(' ');
            return (
              <article
                key={record.run_id}
                className="grid gap-4 p-4 transition-colors hover:bg-[var(--color-bg)] sm:p-5 lg:grid-cols-[1.3fr_0.7fr_0.8fr_1.6fr] lg:items-center"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-base font-semibold">
                      {date}
                    </span>
                    <span className="font-mono text-base text-[var(--color-muted)]">
                      {time}
                    </span>
                    <span className="rounded-full bg-[var(--color-border)] px-2 py-0.5 text-[11px] text-[var(--color-muted)]">
                      {confidenceLabels[record.confidence]}
                    </span>
                  </div>
                  <div className="mt-1.5 text-xs text-[var(--color-muted)]">
                    {record.direction === 'home_to_work'
                      ? '上班方向 →'
                      : '← 下班方向'}{' '}
                    · {record.distance_km} km
                  </div>
                </div>

                <div>
                  <div className="text-xs text-[var(--color-muted)]">耗时</div>
                  <div className="mt-1 font-mono text-lg font-semibold">
                    {record.moving_time}
                  </div>
                </div>

                <div>
                  <div className="text-xs text-[var(--color-muted)]">
                    平均速度
                  </div>
                  <div className="mt-1 font-mono text-lg font-semibold">
                    {record.average_speed_kmh}
                    <span className="ml-1 text-xs font-normal text-[var(--color-muted)]">
                      km/h
                    </span>
                  </div>
                  <div className="text-[11px] text-[var(--color-muted)]">
                    {record.average_speed_mps} m/s
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  {decisionOptions.map((option) => (
                    <ReviewChoice
                      key={option.value}
                      option={option}
                      selected={decision === option.value}
                      onClick={() => setDecision(record.run_id, option.value)}
                    />
                  ))}
                </div>
              </article>
            );
          })}

          {visible.length === 0 && (
            <div className="p-12 text-center text-sm text-[var(--color-muted)]">
              当前筛选条件下没有记录。
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--color-border)] p-4">
          <button
            type="button"
            disabled={currentPage === 0}
            onClick={() => setPage(Math.max(0, currentPage - 1))}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm disabled:opacity-30"
          >
            ← 上一页
          </button>
          <span className="text-sm text-[var(--color-muted)]">
            第 {currentPage + 1} / {totalPages} 页
          </span>
          <button
            type="button"
            disabled={currentPage >= totalPages - 1}
            onClick={() => setPage(Math.min(totalPages - 1, currentPage + 1))}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm disabled:opacity-30"
          >
            下一页 →
          </button>
        </div>
      </section>
    </main>
  );
}
