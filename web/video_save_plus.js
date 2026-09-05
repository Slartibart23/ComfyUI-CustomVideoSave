import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "VideoSavePlus";

function toast(severity, summary, detail) {
    const t = app.extensionManager?.toast;
    if (t?.add) {
        t.add({ severity, summary, detail, life: severity === "error" ? 6000 : 3500 });
    } else if (severity === "error") {
        alert(`${summary}\n${detail ?? ""}`);
    } else {
        console.log(`[VideoSavePlus] ${summary} ${detail ?? ""}`);
    }
}

async function callAction(node, action, extra = {}) {
    try {
        const res = await api.fetchApi("/video_save_plus/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, node_id: String(node.id), ...extra }),
        });
        const data = await res.json();
        if (data.ok) {
            toast("success", "Video Save Plus", data.message);
        } else {
            toast("warn", "Video Save Plus", data.message);
        }
        return data;
    } catch (e) {
        toast("error", "Video Save Plus", String(e));
        return { ok: false };
    }
}

function buildStatusElement() {
    const wrap = document.createElement("div");
    Object.assign(wrap.style, {
        display: "flex",
        flexDirection: "column",
        gap: "4px",
        width: "100%",
        height: "100%",
        boxSizing: "border-box",
        padding: "4px 6px",
        overflow: "hidden",
        fontSize: "11px",
        fontFamily: "sans-serif",
        color: "#ccc",
    });

    const line1 = document.createElement("div");
    line1.textContent = "No generation in this session yet.";
    line1.style.whiteSpace = "nowrap";
    line1.style.overflow = "hidden";
    line1.style.textOverflow = "ellipsis";

    const line2 = document.createElement("div");
    line2.style.fontWeight = "bold";

    const video = document.createElement("video");
    video.controls = true;
    video.muted = false;
    video.preload = "metadata";
    Object.assign(video.style, {
        width: "100%",
        flex: "1 1 auto",
        minHeight: "0",
        background: "#111",
        borderRadius: "4px",
        display: "none",
        objectFit: "contain",
    });

    wrap.append(line1, line2, video);
    return { wrap, line1, line2, video };
}

app.registerExtension({
    name: "Comfy.VideoSavePlus.Buttons",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const ret = onNodeCreated?.apply(this, arguments);
            const node = this;

            const opts = { serialize: false };

            node.addWidget("button", "📂 Reveal in file manager", null,
                () => callAction(node, "reveal"), opts);

            node.addWidget("button", "▶ Open video (with sound)", null,
                () => callAction(node, "open_video"), opts);

            node.addWidget("button", "🖼 Save Last Frame", null,
                () => callAction(node, "save_last_frame"), opts);

            node.addWidget("button", "💾 Save Training File", null, () => {
                const w = node.widgets?.find((x) => x.name === "copy_to_folder");
                const target = (w?.value ?? "").trim();
                if (!target) {
                    toast("warn", "Video Save Plus", "Enter a folder in 'copy_to_folder' first.");
                    return;
                }
                callAction(node, "copy", { target });
            }, opts);

            node.addWidget("button", "🗑 Delete Last Generation", null, async () => {
                const base = node._vspStatus?.base ?? "the last generation";
                const files = node._vspStatus?.files?.join("\n  ") ?? "";
                const ok = confirm(
                    `Delete ${base}?\n\nFiles:\n  ${files}\n\nThis cannot be undone.`
                );
                if (!ok) return;
                const res = await callAction(node, "delete");
                if (res.ok) {
                    node._vspStatus = null;
                    node._vspUI.line1.textContent = "Last generation deleted.";
                    node._vspUI.line2.textContent = "";
                    node._vspUI.video.style.display = "none";
                    node._vspUI.video.removeAttribute("src");
                    node._vspUI.video.load();
                }
            }, opts);

            // status + inline preview
            const ui = buildStatusElement();
            node._vspUI = ui;
            node.addDOMWidget("vsp_status", "VSP_STATUS", ui.wrap, {
                serialize: false,
                hideOnZoom: false,
                getMinHeight: () => 60,
            });

            node.setSize([Math.max(node.size[0], 360), node.computeSize()[1] + 180]);
            return ret;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const s = message?.vsp_status?.[0];
            if (!s || !this._vspUI) return;
            this._vspStatus = s;

            const { line1, line2, video } = this._vspUI;
            const mode = s.passthrough ? " · passthrough (no re-encode)" : "";
            line1.textContent = `${s.base}.mp4 · ${s.resolution} · ${s.frames} fr @ ${s.fps} fps · ${s.duration}s · ${s.size_mb} MB${mode}`;
            line1.title = s.video;
            if (s.has_audio) {
                line2.textContent = `✓ Audio: ${s.audio}`;
                line2.style.color = "#7fd67f";
            } else {
                line2.textContent = `⚠ No audio (${s.audio})`;
                line2.style.color = "#f0b04a";
            }

            video.src = api.apiURL(`/video_save_plus/file?node_id=${encodeURIComponent(String(this.id))}&t=${Date.now()}`);
            video.style.display = "block";
            video.load();
            this.setDirtyCanvas(true, true);
        };
    },
});
