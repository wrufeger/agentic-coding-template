# Lesson template

A lesson is `lessons/NNNN-<slug>.md`, in the language set by `teach-lessons`.

````markdown
# NNNN - <Title>

> Topic: <topic> - builds on: <earlier lesson links, or "none">

## Overview
<A few paragraphs. Each claim names its source: [source](url) or `<path>:<line>`.>

## Examples
<Code from the project first, with `<path>:<line>`; otherwise minimal and valid for the installed version.>

## Exercises
The exercises live in `exercises/NNNN-<slug>/` (named like this lesson), one subfolder per exercise
with its task and check. Run the checks: `<command>`

1. <task> - `<subfolder>`
2. <task> - `<subfolder>`

## Questions
1. <recall question>
2. <application question>
3. <transfer question>
4. <question from an earlier lesson - from lesson 2 on; lesson 1 has none>

<details>
<summary>Answers</summary>

1. <answer>
2. <answer>
3. <answer>
4. <answer>

</details>

## Further reading
<One main source.>
````

Multiple-choice answers are equally long and the right one changes position from question to question.
