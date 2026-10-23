/**
 * What the rail says, and what it deliberately does not.
 *
 * There was no test file here at all, which is how `no_entry_node` came to be
 * printed in monospace under an otherwise good sentence for a whole release.
 */
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProblemsRail } from "./ProblemsRail";
import { makeDetail, makeSampleGraph } from "../test/fixtures";
import { makeStore, renderWith } from "../test/render";

const withIssues = (errors: { code: string; message: string }[]) =>
  makeStore(makeDetail(makeSampleGraph(), { validation: { errors, warnings: [] } }));

describe("ProblemsRail", () => {
  it("renders an issue without exposing its internal code", () => {
    const store = withIssues([{ code: "no_entry_node", message: "O fluxo não tem etapas para executar. Adicione uma antes de ativá-lo." }]);

    const { container } = renderWith(store, <ProblemsRail />);

    expect(container.querySelector('[data-code="no_entry_node"]')).not.toBeNull();
    expect(screen.queryByText("no_entry_node")).toBeNull();
  });

  it("deduplicates repeated issues", () => {
    // multiple_entry_nodes is emitted per node by apps/flows/schema/validation.py.
    // railIssues dedupes on code|message from the data, so hiding the code
    // changes nothing about which issues survive.
    const store = withIssues([
      { code: "multiple_entry_nodes", message: "Mais de uma etapa inicia este fluxo." },
      { code: "multiple_entry_nodes", message: "Mais de uma etapa inicia este fluxo." },
    ]);

    renderWith(store, <ProblemsRail />);

    expect(document.querySelectorAll('[data-code="multiple_entry_nodes"]')).toHaveLength(1);
  });

  it("renders an issue code this bundle has never seen", () => {
    const store = withIssues([{ code: "a_code_from_a_later_layer", message: "Algo verificado por uma camada posterior." }]);

    const { container } = renderWith(store, <ProblemsRail />);

    expect(container.querySelector('[data-code="a_code_from_a_later_layer"]')).not.toBeNull();
  });

  it("opens trigger settings from the all-off warning", () => {
    const store = makeStore(makeDetail(makeSampleGraph(), {
      validation: { errors: [], warnings: [{ code: "flow_triggers_all_disabled", message: "Todos os gatilhos estão desativados." }] },
    }));
    const opened = vi.fn();
    window.addEventListener("toggle-triggers", opened);
    try {
      renderWith(store, <ProblemsRail />);
      fireEvent.click(screen.getByRole("button", { name: /Abrir configurações dos gatilhos/ }));
      expect(opened).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener("toggle-triggers", opened);
    }
  });
});
