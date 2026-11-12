import json
from pathlib import Path
import tempfile

import folder_paths

from .capture import capture, config, resolve_input, snapshot_prompt


def inputs():
    return {"project": ("STRING", {"default": "Мой проект"}),
            "artifact": ("STRING", {"default": "Мой артефакт"})}


class ArchiveImages:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), **inputs()},
                "optional": {"metadata": ("VAULT_METADATA",)},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "version_url")
    FUNCTION = "archive"
    OUTPUT_NODE = True
    CATEGORY = "Comfy Vault"
    DESCRIPTION = "Сохранить результаты, исходные файлы и workflow как новую версию. Веса моделей не копируются."

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # A repeated queued execution is a new iteration even if upstream nodes are cached.
        return float("nan")

    def archive(self, images, project, artifact, prompt=None, extra_pnginfo=None, unique_id=None, metadata=None):
        if not prompt or unique_id is None:
            raise RuntimeError("ComfyUI не передал граф запуска и ID архивирующей ноды")
        prompt = snapshot_prompt(prompt)
        import numpy as np
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        with tempfile.TemporaryDirectory(prefix="comfy-vault-") as scratch:
            outputs = []
            for index, image in enumerate(images):
                path = Path(scratch) / f"image_{index:04}.png"
                pixels = np.clip(image.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
                info = PngInfo()
                info.add_text("prompt", json.dumps(prompt, ensure_ascii=False, allow_nan=False))
                if (extra_pnginfo or {}).get("workflow"):
                    info.add_text("workflow", json.dumps(extra_pnginfo["workflow"], ensure_ascii=False, allow_nan=False))
                Image.fromarray(pixels).save(path, pnginfo=info)
                outputs.append({"source": path, "name": path.name, "batch_index": index})
            result, url = capture(project, artifact, prompt, (extra_pnginfo or {}).get("workflow"), unique_id,
                                  outputs, metadata, folder_paths, scratch)
        print(f"[Comfy Vault] Версия {result.get('number', result['id'])} сохранена: {url}")
        return {"ui": {"text": [f"Сохранено: {url}"]}, "result": (images, url)}


class ArchiveFiles:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {**inputs(), "files": ("STRING", {"default": "", "multiline": True,
                    "tooltip": "Готовые файлы в input/output/temp: один абсолютный путь на строку или имя относительно input. Веса запрещены."})},
                "optional": {"vhs_filenames": ("VHS_FILENAMES",), "metadata": ("VAULT_METADATA",),
                             "after": ("*", {"forceInput": True, "tooltip": "Выход ноды сохранения: задаёт порядок выполнения и ветку параметров."})},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("version_url",)
    FUNCTION = "archive"
    OUTPUT_NODE = True
    CATEGORY = "Comfy Vault"
    IS_CHANGED = ArchiveImages.IS_CHANGED

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def archive(self, project, artifact, files="", vhs_filenames=None, metadata=None,
                prompt=None, extra_pnginfo=None, unique_id=None, after=None):
        if not prompt or unique_id is None:
            raise RuntimeError("ComfyUI не передал граф запуска")
        paths = [x.strip() for x in files.splitlines() if x.strip()]
        if vhs_filenames:
            if not isinstance(vhs_filenames, (tuple, list)) or len(vhs_filenames) != 2:
                raise ValueError("Неизвестный формат VHS_FILENAMES")
            paths.extend(str(x) for x in vhs_filenames[1])
        outputs, seen = [], set()
        settings = config()
        for value in paths:
            full = resolve_input(value, folder_paths, settings)
            if full is None:
                raise ValueError(f"Файл не найден, находится вне разрешённых каталогов или является весами: {value}")
            if full not in seen:
                outputs.append({"source": full, "name": full.name})
                seen.add(full)
        if not outputs:
            raise ValueError("Передайте пути готовых файлов или выход VHS_FILENAMES")
        with tempfile.TemporaryDirectory(prefix="comfy-vault-") as scratch:
            result, url = capture(project, artifact, prompt, (extra_pnginfo or {}).get("workflow"), unique_id,
                                  outputs, metadata, folder_paths, scratch)
        return {"ui": {"text": [f"Сохранено: {url}"]}, "result": (url,)}


class CaptureValue:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"value": ("*", {"forceInput": True}), "name": ("STRING", {"default": "seed"})},
                "optional": {"previous": ("VAULT_METADATA",)}}

    RETURN_TYPES = ("*", "VAULT_METADATA")
    RETURN_NAMES = ("value", "metadata")
    FUNCTION = "collect"
    CATEGORY = "Comfy Vault"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def collect(self, value, name, previous=None):
        # Validate the complete chain, including metadata supplied by other nodes.
        if not name.strip():
            raise ValueError("Укажите название параметра")
        if previous is not None and not isinstance(previous, dict):
            raise ValueError("Capture Value.previous должен содержать словарь метаданных")
        result = {**(previous or {}), name.strip(): value}
        try:
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as error:
            raise ValueError("Capture Value: параметры должны быть JSON-значениями без NaN/Infinity; передайте число, текст, список или словарь") from error
        if len(serialized) > 1024**2:
            raise ValueError("Capture Value предназначена для небольших параметров")
        return value, json.loads(serialized)


NODE_CLASS_MAPPINGS = {"ComfyVaultArchiveImages": ArchiveImages, "ComfyVaultArchiveFiles": ArchiveFiles,
                       "ComfyVaultCaptureValue": CaptureValue}
NODE_DISPLAY_NAME_MAPPINGS = {"ComfyVaultArchiveImages": "Archive Images · Comfy Vault",
                             "ComfyVaultArchiveFiles": "Archive Files · Comfy Vault",
                             "ComfyVaultCaptureValue": "Capture Value · Comfy Vault"}
