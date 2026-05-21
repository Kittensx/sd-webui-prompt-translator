# Roundtrip Translation Testing

This diagnostic checks whether prompts survive multi-language translation without corrupting Stable Diffusion syntax.

It runs:

```text
English -> language B -> language C -> language D
```

At each stage it also translates the current result back to the anchor language, usually English, so drift can be measured early. At the end it runs the full reverse chain back to English.

## Quick smoke test

Start with one provider and one prompt:

```bash
python language/roundtrip_translation_test.py --providers argos --max-prompts 1
```

or:

```bash
python language/roundtrip_translation_test.py --providers nllb --max-prompts 1
```

## Full default test

```bash
python language/roundtrip_translation_test.py
```

The default provider list is:

```text
argos nllb static_dictionary
```

`smart` is not included by default because it internally compares multiple providers and can duplicate model work during diagnostics. To test smart routing explicitly:

```bash
python language/roundtrip_translation_test.py --providers smart --max-prompts 1
```

## Custom language chain

```bash
python language/roundtrip_translation_test.py --languages ja fr de
```

This means:

```text
en -> ja -> fr -> de -> en
```

## Custom prompt file

Create a newline-separated text file:

```text
(cat:1.2), lake, {duck, lake, woman}
<lora:add_detail:0.8>, BREAK, cinematic lighting, [bad hands:0.5]
```

Then run:

```bash
python language/roundtrip_translation_test.py --prompts my_prompts.txt --providers nllb
```

## Output files

The script writes:

```text
test_outputs/roundtrip_translation_results.json
test_outputs/roundtrip_translation_results.csv
```

## About repeated "Loading weights" messages

The test harness now caches provider instances and the NLLB model object. NLLB should load once per model/device combination, then be reused across stages and prompts.

If weights still load repeatedly, check that:

1. You are not launching a fresh Python process for every prompt.
2. You are not testing `smart` and `nllb` together unless you intentionally want duplicated comparison paths.
3. The model path/device is not changing between calls.

For fastest debugging, use:

```bash
python language/roundtrip_translation_test.py --providers nllb --max-prompts 1
```
