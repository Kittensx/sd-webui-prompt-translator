from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

import gradio as gr

try:
    from modules import script_callbacks, scripts, shared
except Exception:  # standalone import tests
    script_callbacks = None
    scripts = None
    shared = None

EXTENSION_ROOT = Path(__file__).resolve().parents[1]
LANGUAGE_DIR = EXTENSION_ROOT / "language"
if str(LANGUAGE_DIR) not in sys.path:
    sys.path.insert(0, str(LANGUAGE_DIR))

from prompt_translator_service import PromptTranslatorService, register_a1111_bridge

SERVICE = PromptTranslatorService(extension_root=EXTENSION_ROOT)
BRIDGE_STATUS = register_a1111_bridge(SERVICE)

_PROMPT_COMPS: Dict[str, Any] = {}


def _capture_prompt_components(component, **kwargs):
    elem_id = kwargs.get("elem_id") or getattr(component, "elem_id", "")
    if elem_id == "txt2img_prompt":
        _PROMPT_COMPS["txt2img"] = component
    elif elem_id == "img2img_prompt":
        _PROMPT_COMPS["img2img"] = component
    elif elem_id == "txt2img_neg_prompt":
        _PROMPT_COMPS["txt2img_negative"] = component
    elif elem_id == "img2img_neg_prompt":
        _PROMPT_COMPS["img2img_negative"] = component


if script_callbacks is not None:
    try:
        script_callbacks.on_after_component(_capture_prompt_components)
    except Exception:
        pass


LANG_CHOICES = [(name, code) for code, name in SERVICE.language_choices()]
TARGET_CHOICES = [("My language", "user")] + LANG_CHOICES
SOURCE_CHOICES = [("Auto-detect", "auto")] + LANG_CHOICES
MODE_CHOICES = [("Prompt-safe", "prompt"), ("Natural language", "natural_language"), ("Search query", "search")]
PROVIDER_CHOICES = SERVICE.provider_choices()


def _json_pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _format_status(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return str(payload)
    if payload.get("error"):
        return f"Error: {payload.get('error')}"
    lines = []
    if "translation" in payload:
        lines.append(f"Translation: {payload.get('translation')}")
    if payload.get("provider"):
        lines.append(f"Provider: {payload.get('provider')}")
    if payload.get("score") is not None:
        lines.append(f"Score: {payload.get('score')}")
    lines.append(f"Source: {payload.get('source_language', '')} -> Target: {payload.get('target_language', '')}")
    return "\n".join(lines)


def _save_settings(user_language, source_language, target_language, provider, mode, auto_detect, show_compare):
    saved = SERVICE.update_settings(
        user_language=user_language,
        source_language=source_language,
        target_language=target_language,
        provider_mode=provider,
        translation_mode=mode,
        auto_detect_source=bool(auto_detect),
        show_provider_comparison=bool(show_compare),
    )
    return "Saved settings:\n" + _json_pretty(saved)


def _translate_text(text, source_language, target_language, provider, mode, auto_detect):
    result = SERVICE.translate_text(
        text or "",
        source_language=source_language,
        target_language=target_language,
        provider=provider,
        mode=mode,
        auto_detect=bool(auto_detect),
    )
    return result.get("translation", text or ""), _format_status(result), _json_pretty(result)


def _compare_text(text, source_language, target_language, mode):
    result = SERVICE.compare_providers(text or "", source_language=source_language, target_language=target_language, mode=mode)
    lines = []
    winner = result.get("winner") or {}
    if winner:
        lines.append(f"Smart pick: {winner.get('provider')} | score={winner.get('score')} | {winner.get('text')}")
        lines.append("")
    for cand in result.get("candidates") or []:
        lines.append(f"{cand.get('provider')} | score={cand.get('score')}")
        lines.append(str(cand.get("text") or ""))
        reasons = cand.get("reasons") or []
        penalties = cand.get("penalties") or []
        if reasons:
            lines.append("  + " + "; ".join(reasons))
        if penalties:
            lines.append("  - " + "; ".join(penalties))
        lines.append("")
    return "\n".join(lines).strip(), _json_pretty(result)


def _translate_selection(selection_json, source_language, target_language, provider, mode, auto_detect):
    try:
        result = SERVICE.replace_selection_payload(
            selection_json or "{}",
            source_language=source_language,
            target_language=target_language,
            provider=provider,
            mode=mode,
        )
        status = _format_status(result)
        return result.get("updated_prompt", ""), status, _json_pretty(result)
    except Exception as e:
        payload = {"ok": False, "error": repr(e), "traceback": traceback.format_exc()}
        return "", "Selection translation failed: " + repr(e), _json_pretty(payload)


def _provider_status():
    payload = SERVICE.provider_status()
    return _format_provider_status(payload), _json_pretty(payload)


def _format_provider_status(payload: Dict[str, Any]) -> str:
    if payload.get("error"):
        return "Error: " + str(payload.get("error"))
    lines = []
    argos_dep = payload.get("argos_dependency") or {}
    lines.append(f"Argos installed: {argos_dep.get('installed')} ({argos_dep.get('version') or 'unknown version'})")
    pairs = payload.get("argos_installed_pairs") or []
    lines.append(f"Argos installed pairs: {len(pairs)}")
    if pairs:
        preview = ", ".join(f"{p.get('source_language')}->{p.get('target_language')}" for p in pairs[:20])
        lines.append("Pairs: " + preview + (" ..." if len(pairs) > 20 else ""))
    nllb_deps = payload.get("nllb_dependencies") or {}
    lines.append("NLLB dependencies:")
    for key, rec in nllb_deps.items():
        lines.append(f"  {key}: {rec.get('installed')}")
    nllb_rows = payload.get("nllb_lightweight") or []
    installed_nllb = any(r.get("installed") for r in nllb_rows)
    lines.append(f"NLLB model installed: {installed_nllb}")
    dict_status = payload.get("dictionary_status") or {}
    manifest = dict_status.get("manifest") or {}
    lines.append(f"Installed dictionaries: {manifest.get('installed_count', 0)}")
    return "\n".join(lines)


def _argos_available(bundle, update_index):
    payload = SERVICE.argos_available_matrix(bundle=bundle, update_index=bool(update_index))
    if not payload.get("ok"):
        return "Error: " + str(payload.get("error")), _json_pretty(payload)
    rows = payload.get("rows") or []
    lines = [f"Argos available matrix ({bundle})"]
    for row in rows:
        status = "installed" if row.get("installed") else ("available" if row.get("available") else "missing")
        lines.append(f"{row.get('source_language')} -> {row.get('target_language')}: {status}")
    return "\n".join(lines), _json_pretty(payload)


def _install_argos_bundle(bundle):
    payload = SERVICE.install_argos_bundle(bundle=bundle)
    lines = [f"Argos bundle install: {bundle}"]
    lines.append(f"Installed: {len(payload.get('installed_pairs') or [])}")
    lines.append(f"Skipped: {len(payload.get('skipped_pairs') or [])}")
    errors = payload.get("errors") or []
    if errors:
        lines.append("Errors:")
        lines.extend("  " + str(e) for e in errors[:20])
    return "\n".join(lines), _json_pretty(payload)


def _install_argos_pair(src, tgt):
    payload = SERVICE.install_argos_pair(src, tgt)
    return _json_pretty(payload), _json_pretty(payload)


def _install_nllb(model_id, force):
    payload = SERVICE.install_nllb_model(model_id=model_id or "facebook/nllb-200-distilled-600M", force=bool(force))
    return _json_pretty(payload), _json_pretty(payload)


def _dictionary_status():
    payload = SERVICE.dictionary_status()
    if not payload.get("ok"):
        return "Error: " + str(payload.get("error")), _json_pretty(payload)
    manifest = payload.get("manifest") or {}
    rows = manifest.get("dictionaries") or []
    lines = [f"Installed dictionaries: {len(rows)}"]
    for row in rows[:50]:
        lines.append(f"{row.get('source_language')} -> {row.get('target_language')}: {row.get('name')} ({row.get('record_count')} records)")
    if not rows:
        lines.append("No installed dictionaries yet. Import a JSON/TSV file or download from a direct dictionary URL.")
    return "\n".join(lines), _json_pretty(payload)


def _import_dictionary(file_path, src, tgt, name):
    payload = SERVICE.import_dictionary(file_path or "", source_language=src, target_language=tgt, name=name or "")
    return _json_pretty(payload), _json_pretty(payload)


def _download_dictionary(url, src, tgt, name):
    payload = SERVICE.download_dictionary(url or "", source_language=src, target_language=tgt, name=name or "downloaded")
    return _json_pretty(payload), _json_pretty(payload)


def _write_dictionary_template():
    payload = SERVICE.write_dictionary_sources_template()
    return _json_pretty(payload), _json_pretty(payload)

def _open_folder(path: str) -> str:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(p)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(p)])
        return f"Opened: {p}"
    except Exception as e:
        return f"Could not open folder: {p}\n{e!r}"


def build_ui(is_img2img: bool):
    settings = SERVICE.settings
    prompt_comp = _PROMPT_COMPS.get("img2img" if is_img2img else "txt2img")
    main_prompt_input = prompt_comp if prompt_comp is not None else gr.State(value="")

    with gr.Accordion("Prompt Translator", open=False):
        gr.Markdown(
            "Translate selected prompt text using offline-first providers. "
            "Prompt-safe mode tries to preserve short tag/phrase behavior instead of rewriting as prose."
        )

        selection_state = gr.Textbox(value="{}", visible=False, elem_id=("prompt_translator_selection_img2img" if is_img2img else "prompt_translator_selection_txt2img"))
        undo_state = gr.State(value="")

        with gr.Row():
            user_language = gr.Dropdown(choices=LANG_CHOICES, value=settings.user_language, label="My language")
            auto_detect = gr.Checkbox(value=settings.auto_detect_source, label="Auto-detect source")
            source_language = gr.Dropdown(choices=SOURCE_CHOICES, value=settings.source_language, label="From")
            target_language = gr.Dropdown(choices=TARGET_CHOICES, value=settings.target_language, label="To")

        with gr.Row():
            provider = gr.Dropdown(choices=PROVIDER_CHOICES, value=settings.provider_mode, label="Provider")
            mode = gr.Dropdown(choices=MODE_CHOICES, value=settings.translation_mode, label="Mode")
            show_compare = gr.Checkbox(value=settings.show_provider_comparison, label="Show comparisons")
            save_settings_btn = gr.Button("Save language settings")

        settings_status = gr.Textbox(label="Settings/status", lines=3)

        with gr.Row():
            translate_selection_btn = gr.Button("Translate selected prompt text")
            translate_whole_btn = gr.Button("Translate whole prompt")
            compare_btn = gr.Button("Compare providers")
            undo_btn = gr.Button("Undo last translation")

        translated_working = gr.Textbox(label="Translated / updated prompt", lines=4)
        compare_out = gr.Textbox(label="Provider comparison", lines=10)
        debug_out = gr.Textbox(label="Debug JSON", lines=10)

        with gr.Accordion("Language packs / provider models", open=False):
            gr.Markdown(
                "Argos packages are downloaded from Argos' package index. NLLB downloads from Hugging Face and uses HF_TOKEN if set. "
                "Model binaries are not bundled with this extension."
            )
            with gr.Row():
                provider_status_btn = gr.Button("Refresh provider status")
                open_models_btn = gr.Button("Open models folder")
                open_config_btn = gr.Button("Open config folder")
            provider_status_text = gr.Textbox(label="Provider status", lines=10)
            provider_status_json = gr.Textbox(label="Provider status JSON", lines=10)

            with gr.Row():
                argos_bundle = gr.Dropdown(choices=["lightweight", "full"], value="lightweight", label="Argos bundle")
                argos_update_index = gr.Checkbox(value=True, label="Update Argos package index")
                argos_available_btn = gr.Button("Show available Argos languages")
                argos_install_bundle_btn = gr.Button("Install Argos bundle")

            with gr.Row():
                argos_src = gr.Dropdown(choices=LANG_CHOICES, value="en", label="Argos from")
                argos_tgt = gr.Dropdown(choices=LANG_CHOICES, value="ja", label="Argos to")
                argos_install_pair_btn = gr.Button("Install Argos pair")

            with gr.Row():
                nllb_model = gr.Textbox(value="facebook/nllb-200-distilled-600M", label="NLLB model id")
                nllb_force = gr.Checkbox(value=False, label="Force redownload")
                nllb_install_btn = gr.Button("Install NLLB model")

            gr.Markdown("### Optional dictionaries")
            gr.Markdown(
                "Dictionaries are optional and user-installed. Use JSON/TSV files or a direct URL. "
                "They are checked before Argos/NLLB and are best for short prompt fragments."
            )
            with gr.Row():
                dict_status_btn = gr.Button("Refresh dictionary status")
                dict_template_btn = gr.Button("Write dictionary sources template")
                open_dictionaries_btn = gr.Button("Open dictionaries folder")
            with gr.Row():
                dict_src = gr.Dropdown(choices=LANG_CHOICES, value="en", label="Dictionary from")
                dict_tgt = gr.Dropdown(choices=LANG_CHOICES, value="ja", label="Dictionary to")
                dict_name = gr.Textbox(value="custom", label="Dictionary name")
            dict_file_path = gr.Textbox(label="Import local dictionary file", placeholder="C:\\path\\to\\en_ja_dictionary.json or .tsv")
            dict_url = gr.Textbox(label="Download dictionary URL", placeholder="Direct URL to JSON/TSV/TXT dictionary file")
            with gr.Row():
                dict_import_btn = gr.Button("Import dictionary file")
                dict_download_btn = gr.Button("Download dictionary URL")

            install_status = gr.Textbox(label="Install/status output", lines=10)
            install_json = gr.Textbox(label="Install/status JSON", lines=10)

        save_settings_btn.click(
            fn=_save_settings,
            inputs=[user_language, source_language, target_language, provider, mode, auto_detect, show_compare],
            outputs=[settings_status],
        )

        # JS captures browser selection and passes it as first hidden input value.
        translate_selection_btn.click(
            fn=_translate_selection,
            inputs=[selection_state, source_language, target_language, provider, mode, auto_detect],
            outputs=[translated_working, settings_status, debug_out],
            _js=(
                "(selection_state, source_language, target_language, provider, mode, auto_detect) => "
                "[window.promptTranslatorCaptureActiveSelection ? window.promptTranslatorCaptureActiveSelection() : '{}', "
                "source_language, target_language, provider, mode, auto_detect]"
            ),
        ).then(
            fn=lambda old, new: (old, new),
            inputs=[main_prompt_input, translated_working],
            outputs=[undo_state, main_prompt_input],
        )

        translate_whole_btn.click(
            fn=_translate_text,
            inputs=[main_prompt_input, source_language, target_language, provider, mode, auto_detect],
            outputs=[translated_working, settings_status, debug_out],
        ).then(
            fn=lambda old, new: (old, new),
            inputs=[main_prompt_input, translated_working],
            outputs=[undo_state, main_prompt_input],
        )

        compare_btn.click(
            fn=_compare_text,
            inputs=[main_prompt_input, source_language, target_language, mode],
            outputs=[compare_out, debug_out],
        )

        undo_btn.click(fn=lambda old: old, inputs=[undo_state], outputs=[main_prompt_input])

        provider_status_btn.click(fn=_provider_status, inputs=[], outputs=[provider_status_text, provider_status_json])
        open_models_btn.click(fn=lambda: _open_folder(str(SERVICE.models_dir)), inputs=[], outputs=[install_status])
        open_config_btn.click(fn=lambda: _open_folder(str(SERVICE.config_dir)), inputs=[], outputs=[install_status])
        argos_available_btn.click(fn=_argos_available, inputs=[argos_bundle, argos_update_index], outputs=[install_status, install_json])
        argos_install_bundle_btn.click(fn=_install_argos_bundle, inputs=[argos_bundle], outputs=[install_status, install_json])
        argos_install_pair_btn.click(fn=_install_argos_pair, inputs=[argos_src, argos_tgt], outputs=[install_status, install_json])
        nllb_install_btn.click(fn=_install_nllb, inputs=[nllb_model, nllb_force], outputs=[install_status, install_json])
        dict_status_btn.click(fn=_dictionary_status, inputs=[], outputs=[install_status, install_json])
        dict_template_btn.click(fn=_write_dictionary_template, inputs=[], outputs=[install_status, install_json])
        open_dictionaries_btn.click(fn=lambda: _open_folder(str(SERVICE.dictionaries_dir)), inputs=[], outputs=[install_status])
        dict_import_btn.click(fn=_import_dictionary, inputs=[dict_file_path, dict_src, dict_tgt, dict_name], outputs=[install_status, install_json])
        dict_download_btn.click(fn=_download_dictionary, inputs=[dict_url, dict_src, dict_tgt, dict_name], outputs=[install_status, install_json])

    return []


if scripts is not None:
    class PromptTranslatorScript(scripts.Script):
        def title(self):
            return "Prompt Translator"

        def show(self, is_img2img):
            return scripts.AlwaysVisible

        def ui(self, is_img2img):
            return build_ui(is_img2img)

else:
    class PromptTranslatorScript:  # standalone import fallback
        pass
