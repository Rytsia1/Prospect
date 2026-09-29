"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/documents";
import {
  calculateScenarioPreview,
  createScenario,
  deleteScenario,
  listScenarios,
  type Scenario,
  type ScenarioCalculationResult,
} from "@/lib/phase6";

export default function ScenariosPage() {
  // Model Inputs
  const [baseRevenue, setBaseRevenue] = useState("12400000000000");
  const [baseNetIncome, setBaseNetIncome] = useState("1740000000000");
  const [revenueGrowthPct, setRevenueGrowthPct] = useState("5.0");
  const [netMarginPct, setNetMarginPct] = useState("14.0");

  // Live Preview Result
  const [preview, setPreview] = useState<ScenarioCalculationResult | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Saved Scenarios
  const [savedScenarios, setSavedScenarios] = useState<Scenario[] | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(true);

  // Save Modal
  const [showSave, setShowSave] = useState(false);
  const [scenarioName, setScenarioName] = useState("");
  const [scenarioDesc, setScenarioDesc] = useState("");
  const [basePeriod, setBasePeriod] = useState("FY2025");
  const [saving, setSaving] = useState(false);

  const runPreview = useCallback(async () => {
    if (!baseRevenue.trim()) return;
    try {
      setCalculating(true);
      const res = await calculateScenarioPreview({
        base_revenue: baseRevenue.trim(),
        base_net_income: baseNetIncome.trim() || undefined,
        revenue_growth_pct: revenueGrowthPct.trim() || "0.0",
        net_margin_pct: netMarginPct.trim() || undefined,
      });
      setPreview(res);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Calculation failed.");
    } finally {
      setCalculating(false);
    }
  }, [baseRevenue, baseNetIncome, revenueGrowthPct, netMarginPct]);

  const loadSaved = useCallback(async () => {
    try {
      setLoadingSaved(true);
      const res = await listScenarios();
      setSavedScenarios(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load saved scenarios.");
    } finally {
      setLoadingSaved(false);
    }
  }, []);

  useEffect(() => {
    runPreview();
  }, [runPreview]);

  useEffect(() => {
    loadSaved();
  }, [loadSaved]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!scenarioName.trim() || !baseRevenue.trim()) return;
    try {
      setSaving(true);
      await createScenario({
        name: scenarioName.trim(),
        description: scenarioDesc.trim() || null,
        base_period: basePeriod.trim(),
        base_revenue: baseRevenue.trim(),
        base_net_income: baseNetIncome.trim() || null,
        revenue_growth_pct: revenueGrowthPct.trim() || "0.0",
        net_margin_pct: netMarginPct.trim() || null,
      });
      setShowSave(false);
      setScenarioName("");
      setScenarioDesc("");
      await loadSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save scenario.");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteScenario = async (id: string) => {
    if (!confirm("Are you sure you want to delete this scenario?")) return;
    try {
      await deleteScenario(id);
      await loadSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete scenario.");
    }
  };

  const loadPreset = (s: Scenario) => {
    setBaseRevenue(s.base_revenue);
    setBaseNetIncome(s.base_net_income || "");
    setRevenueGrowthPct(s.revenue_growth_pct);
    setNetMarginPct(s.net_margin_pct || "14.0");
    setBasePeriod(s.base_period);
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Scenario Analysis</h1>
        <p className="text-sm text-slate-500">
          User-controlled mathematical scenarios based on canonical financial facts.
        </p>
      </div>

      {/* Mandatory Regulatory / Research Disclaimer */}
      <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-4 text-xs text-amber-900">
        <strong className="font-semibold uppercase tracking-wider">Disclaimer:</strong> Scenario
        values are user-defined calculations and are not forecasts or investment recommendations.
        Canonical reported figures remain completely unchanged.
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {/* Interactive Scenario Calculator */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Inputs & Sliders */}
        <div className="space-y-5 rounded-lg border border-slate-200 bg-white p-5 shadow-xs">
          <h2 className="text-base font-semibold text-slate-900">Scenario Assumptions</h2>

          <div className="space-y-4">
            <div>
              <label htmlFor="base-rev" className="block text-xs font-medium text-slate-700">
                Base Revenue (Full currency units, e.g. IDR)
              </label>
              <input
                id="base-rev"
                type="text"
                value={baseRevenue}
                onChange={(e) => setBaseRevenue(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 font-mono text-sm"
              />
              <div className="mt-1 text-xs text-slate-400">
                Compact: {formatAmount(baseRevenue || "0", "IDR")}
              </div>
            </div>

            <div>
              <label htmlFor="base-ni" className="block text-xs font-medium text-slate-700">
                Base Net Income (Optional)
              </label>
              <input
                id="base-ni"
                type="text"
                value={baseNetIncome}
                onChange={(e) => setBaseNetIncome(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 font-mono text-sm"
              />
              <div className="mt-1 text-xs text-slate-400">
                Compact: {formatAmount(baseNetIncome || "0", "IDR")}
              </div>
            </div>

            <div className="pt-2 border-t border-slate-200">
              <div className="flex items-center justify-between text-xs font-medium text-slate-700">
                <label htmlFor="growth-slider">Revenue Growth Adjustment</label>
                <span className="font-mono text-sm font-semibold text-slate-900">
                  {Number.parseFloat(revenueGrowthPct) >= 0 ? "+" : ""}
                  {revenueGrowthPct}%
                </span>
              </div>
              <input
                id="growth-slider"
                type="range"
                min="-50"
                max="50"
                step="0.5"
                value={revenueGrowthPct}
                onChange={(e) => setRevenueGrowthPct(e.target.value)}
                className="mt-2 w-full accent-slate-900 cursor-pointer"
              />
              <div className="flex justify-between text-[10px] text-slate-400">
                <span>-50%</span>
                <span>0%</span>
                <span>+50%</span>
              </div>
            </div>

            <div className="pt-2 border-t border-slate-200">
              <div className="flex items-center justify-between text-xs font-medium text-slate-700">
                <label htmlFor="margin-slider">Scenario Net Margin %</label>
                <span className="font-mono text-sm font-semibold text-slate-900">
                  {netMarginPct}%
                </span>
              </div>
              <input
                id="margin-slider"
                type="range"
                min="0"
                max="50"
                step="0.5"
                value={netMarginPct}
                onChange={(e) => setNetMarginPct(e.target.value)}
                className="mt-2 w-full accent-slate-900 cursor-pointer"
              />
              <div className="flex justify-between text-[10px] text-slate-400">
                <span>0%</span>
                <span>25%</span>
                <span>50%</span>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => setShowSave(true)}
                className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
              >
                Save This Scenario
              </button>
            </div>
          </div>
        </div>

        {/* Right: Calculated Outputs */}
        <div className="space-y-5 rounded-lg border border-slate-200 bg-slate-50/70 p-5">
          <h2 className="text-base font-semibold text-slate-900">Deterministic Model Output</h2>

          {calculating ? (
            <div className="py-12 text-center text-xs text-slate-500">Calculating outputs...</div>
          ) : preview ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Reported Base Revenue</span>
                  <span className="font-mono">{formatAmount(preview.base_revenue, "IDR")}</span>
                </div>
                <div className="mt-2 flex items-baseline justify-between">
                  <div className="text-sm font-medium text-slate-700">Scenario Revenue</div>
                  <div className="text-2xl font-semibold tracking-tight text-slate-900 font-mono">
                    {formatAmount(preview.scenario_revenue, "IDR")}
                  </div>
                </div>
                <div className="mt-1 flex items-center justify-end gap-2 text-xs">
                  <span className="text-slate-500">Growth:</span>
                  <span
                    className={`font-semibold ${
                      preview.revenue_growth_pct.startsWith("-")
                        ? "text-rose-600"
                        : "text-emerald-600"
                    }`}
                  >
                    {Number.parseFloat(preview.revenue_growth_pct) >= 0 ? "+" : ""}
                    {preview.revenue_growth_pct}%
                  </span>
                  <span className="text-slate-400">
                    ({formatAmount(preview.revenue_change, "IDR")})
                  </span>
                </div>
              </div>

              {preview.scenario_net_income && (
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span>Reported Base Net Income</span>
                    <span className="font-mono">
                      {preview.base_net_income ? formatAmount(preview.base_net_income, "IDR") : "—"}
                    </span>
                  </div>
                  <div className="mt-2 flex items-baseline justify-between">
                    <div className="text-sm font-medium text-slate-700">Scenario Net Income</div>
                    <div className="text-2xl font-semibold tracking-tight text-slate-900 font-mono">
                      {formatAmount(preview.scenario_net_income, "IDR")}
                    </div>
                  </div>
                  <div className="mt-1 flex items-center justify-end gap-2 text-xs">
                    <span className="text-slate-500">Margin:</span>
                    <span className="font-semibold text-slate-900">{preview.net_margin_pct}%</span>
                    {preview.net_income_change && (
                      <span className="text-slate-400">
                        (Diff: {formatAmount(preview.net_income_change, "IDR")})
                      </span>
                    )}
                  </div>
                </div>
              )}

              <div className="rounded border border-slate-200 bg-white p-3 text-[11px] text-slate-500">
                <strong>Calculation Method:</strong> Deterministic Decimal arithmetic.
                <br />
                <code>scenario_revenue = base_revenue × (1 + growth_pct)</code>
                <br />
                <code>scenario_net_income = scenario_revenue × margin_pct</code>
              </div>
            </div>
          ) : (
            <div className="py-12 text-center text-xs text-slate-500">
              Enter base inputs on the left to calculate.
            </div>
          )}
        </div>
      </div>

      {/* Save Scenario Dialog */}
      {showSave && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-xl">
            <h2 className="text-base font-semibold text-slate-900">Save Scenario Model</h2>
            <form onSubmit={handleSave} className="mt-4 space-y-3">
              <div>
                <label htmlFor="scen-name" className="block text-xs font-medium text-slate-700">
                  Scenario Name *
                </label>
                <input
                  id="scen-name"
                  type="text"
                  required
                  value={scenarioName}
                  onChange={(e) => setScenarioName(e.target.value)}
                  placeholder="e.g. Optimistic Revenue Case"
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
                />
              </div>
              <div>
                <label htmlFor="scen-period" className="block text-xs font-medium text-slate-700">
                  Base Period
                </label>
                <input
                  id="scen-period"
                  type="text"
                  value={basePeriod}
                  onChange={(e) => setBasePeriod(e.target.value)}
                  placeholder="e.g. FY2025"
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
                />
              </div>
              <div>
                <label htmlFor="scen-desc" className="block text-xs font-medium text-slate-700">
                  Description / Assumptions (Optional)
                </label>
                <textarea
                  id="scen-desc"
                  rows={2}
                  value={scenarioDesc}
                  onChange={(e) => setScenarioDesc(e.target.value)}
                  placeholder="Assumes +5% loan growth and stable funding costs."
                  className="mt-1 w-full rounded border border-slate-300 p-2 text-xs"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowSave(false)}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !scenarioName.trim()}
                  className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save Scenario"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Saved Scenarios Table */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold tracking-tight text-slate-900">Saved Scenarios</h2>

        {loadingSaved ? (
          <div className="py-6 text-center text-xs text-slate-400">Loading saved scenarios...</div>
        ) : savedScenarios && savedScenarios.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Scenario Name</th>
                  <th className="px-4 py-3">Base Period</th>
                  <th className="px-4 py-3 text-right">Growth %</th>
                  <th className="px-4 py-3 text-right">Net Margin %</th>
                  <th className="px-4 py-3 text-right">Scenario Revenue</th>
                  <th className="px-4 py-3 text-right">Scenario Net Income</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {savedScenarios.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{s.name}</div>
                      {s.description && (
                        <div className="text-xs text-slate-500">{s.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{s.base_period}</td>
                    <td className="px-4 py-3 text-right font-medium">
                      {Number.parseFloat(s.revenue_growth_pct) >= 0 ? "+" : ""}
                      {s.revenue_growth_pct}%
                    </td>
                    <td className="px-4 py-3 text-right text-slate-600">
                      {s.net_margin_pct ? `${s.net_margin_pct}%` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      {formatAmount(s.scenario_revenue, "IDR")}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      {s.scenario_net_income ? formatAmount(s.scenario_net_income, "IDR") : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => loadPreset(s)}
                          className="rounded border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                        >
                          Load
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteScenario(s.id)}
                          className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-red-600"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-300 py-8 text-center text-xs text-slate-500">
            No saved scenarios yet. Use the model above to create and save scenario cases.
          </div>
        )}
      </section>
    </div>
  );
}
