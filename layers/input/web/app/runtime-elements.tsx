"use client";

import { useState } from "react";
import type { MultipleChoiceElement } from "@loke/contracts";

type ElementProps = { element: MultipleChoiceElement; disabled: boolean; onChoose: (text: string) => void };

function MultipleChoiceCard({ element, disabled, onChoose }: ElementProps) {
  const [selected, setSelected] = useState<string>();
  return (
    <fieldset className="runtime-choice" disabled={disabled || !!selected}>
      <legend>{element.question}</legend>
      {element.choices.map((choice) => (
        <button key={choice.id} type="button" aria-pressed={selected === choice.id}
          onClick={() => {
            setSelected(choice.id);
            onChoose(`Selected choice: ${choice.text}\nQuestion: ${element.question}`);
          }}>
          {choice.text}{selected === choice.id ? " · Selected" : ""}
        </button>
      ))}
    </fieldset>
  );
}

const renderers = new Map<string, (props: ElementProps) => React.ReactNode>([
  ["multiple_choice", MultipleChoiceCard],
]);

export function RuntimeElement(props: ElementProps) {
  const Renderer = renderers.get(props.element.type || "");
  return Renderer ? <Renderer {...props} /> : <p role="status">Unsupported response element.</p>;
}
