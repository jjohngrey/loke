"use client";

import { useId, useState } from "react";
import type { MultipleChoiceElement } from "@loke/contracts";

type ElementProps = {
  element: MultipleChoiceElement;
  disabled: boolean;
  onChoose: (choice: string, question: string) => boolean;
};

function MultipleChoiceCard({ element, disabled, onChoose }: ElementProps) {
  const groupId = useId();
  const [selected, setSelected] = useState<string>();
  const [submitted, setSubmitted] = useState(false);
  const selectedChoice = element.choices.find((choice) => choice.id === selected);
  return (
    <fieldset className="runtime-choice" disabled={disabled || submitted}>
      <legend>{element.question}</legend>
      {element.choices.map((choice) => (
        <label
          className={["runtime-choice-option", selected === choice.id ? "selected" : ""].join(" ")}
          key={choice.id}
        >
          <input
            type="radio"
            name={groupId}
            value={choice.id}
            checked={selected === choice.id}
            onChange={() => setSelected(choice.id)}
          />
          <span>{choice.text}</span>
        </label>
      ))}
      {selectedChoice && !submitted && (
        <button
          className="runtime-choice-continue"
          type="button"
          disabled={disabled}
          onClick={() => {
            if (onChoose(selectedChoice.text, element.question)) setSubmitted(true);
          }}
        >
          Continue
        </button>
      )}
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
