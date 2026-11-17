// MUSHY-192: send a video over signal-cli-rest-api (/v2/send, base64 attachment).
const path = require('path');

async function sendVideo({ apiUrl, sender, recipient, filePath, message }, deps = {}) {
    const fs = deps.fs || require('fs');
    const fetchFn = deps.fetch || fetch;
    const b64 = (await fs.promises.readFile(filePath)).toString('base64');
    const res = await fetchFn(`${apiUrl}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            number: sender,
            recipients: [recipient],
            message,
            base64_attachments: [`data:video/mp4;filename=${path.basename(filePath)};base64,${b64}`],
        }),
    });
    if (!res.ok) throw new Error(`signal send failed: ${res.status} ${(await res.text()).slice(0, 300)}`);
}

module.exports = { sendVideo };
