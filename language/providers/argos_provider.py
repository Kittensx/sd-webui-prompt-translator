from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from language.constants import DEFAULT_BRIDGE_LANGUAGE
    from language.language_utils import canonical_lang
except Exception:
    try:
        from ..constants import DEFAULT_BRIDGE_LANGUAGE
        from ..language_utils import canonical_lang
    except Exception:
        from constants import DEFAULT_BRIDGE_LANGUAGE
        from language_utils import canonical_lang


@dataclass
class Provider:
    """
    Offline Argos Translate provider.

    Argos installs language-pair packages, not one universal model. This provider
    now resolves missing direct pairs through installed bridge routes when
    possible, usually via English. For example ja->fr can route ja->en->fr if
    both packages are installed.
    """
    name: str = "argos"
    fallback_to_original: bool = False
    bridge_language: str = DEFAULT_BRIDGE_LANGUAGE
    max_route_hops: int = 3
    last_error: str = ""
    last_route: List[Tuple[str, str]] | None = None

    def is_available(self) -> bool:
        try:
            import argostranslate  # noqa: F401
            return True
        except Exception:
            return False

    def installed_pairs(self) -> List[Tuple[str, str]]:
        try:
            try:
                from language.provider_model_manager import get_installed_argos_pairs
            except Exception:
                from ..provider_model_manager import get_installed_argos_pairs
            return get_installed_argos_pairs()
        except Exception:
            return []

    def supports_pair(self, source_language: str, target_language: str) -> bool:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        return (src, tgt) in set(self.installed_pairs())

    def _installed_language_map(self):
        try:
            from argostranslate import translate
        except Exception as e:
            self.last_error = "Argos provider requires: pip install argostranslate"
            raise RuntimeError(self.last_error) from e
        return {canonical_lang(lang.code): lang for lang in translate.get_installed_languages()}

    def _direct_translation(self, source_language: str, target_language: str):
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        languages = self._installed_language_map()
        from_lang = languages.get(src)
        to_lang = languages.get(tgt)
        if from_lang is None or to_lang is None:
            installed = sorted(languages.keys())
            raise RuntimeError(f"Argos language package not installed for {src}->{tgt}. Installed languages: {installed}")
        translation = from_lang.get_translation(to_lang)
        if translation is None:
            raise RuntimeError(f"Argos translation route is not installed for {src}->{tgt}")
        return translation

    def _translation_graph(self) -> Dict[str, set[str]]:
        graph: Dict[str, set[str]] = {}
        for src, tgt in self.installed_pairs():
            graph.setdefault(canonical_lang(src), set()).add(canonical_lang(tgt))
        return graph

    def find_route(self, source_language: str, target_language: str) -> List[Tuple[str, str]]:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        if src == tgt:
            return []

        graph = self._translation_graph()
        if tgt in graph.get(src, set()):
            return [(src, tgt)]

        bridge = canonical_lang(self.bridge_language)
        if bridge not in {src, tgt} and bridge in graph.get(src, set()) and tgt in graph.get(bridge, set()):
            return [(src, bridge), (bridge, tgt)]

        # Small bounded BFS. This avoids direct-pair-only failure while preventing
        # long translation chains that would create excessive semantic drift.
        queue = deque([(src, [])])
        seen = {src}
        while queue:
            current, path = queue.popleft()
            if len(path) >= max(1, int(self.max_route_hops)):
                continue
            for nxt in sorted(graph.get(current, set())):
                if nxt in seen:
                    continue
                next_path = path + [(current, nxt)]
                if nxt == tgt:
                    return next_path
                seen.add(nxt)
                queue.append((nxt, next_path))
        return []

    def route_status(self, source_language: str, target_language: str) -> Dict[str, object]:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        route = self.find_route(src, tgt)
        return {
            "source_language": src,
            "target_language": tgt,
            "supported": bool(route) or src == tgt,
            "route": [f"{a}->{b}" for a, b in route],
            "installed_pairs": [f"{a}->{b}" for a, b in self.installed_pairs()],
        }

    def _translate_direct(self, text: str, source_language: str, target_language: str) -> str:
        translation = self._direct_translation(source_language, target_language)
        return translation.translate(text)

    def _translate_one(self, text: str, source_language: str, target_language: str) -> str:
        self.last_error = ""
        self.last_route = None
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        if src == tgt or not str(text or "").strip():
            return text

        try:
            route = self.find_route(src, tgt)
            self.last_route = route
            if not route:
                installed = ", ".join(f"{a}->{b}" for a, b in self.installed_pairs()) or "none"
                self.last_error = f"No installed Argos route for {src}->{tgt}. Installed pairs: {installed}"
                if self.fallback_to_original:
                    return text
                raise RuntimeError(self.last_error)

            result = text
            for step_src, step_tgt in route:
                result = self._translate_direct(result, step_src, step_tgt)
            return result
        except Exception as e:
            if not self.last_error:
                self.last_error = repr(e)
            if self.fallback_to_original:
                return text
            raise

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        return [self._translate_one(t, source_language, target_language) for t in texts]


ArgosTranslationProvider = Provider
