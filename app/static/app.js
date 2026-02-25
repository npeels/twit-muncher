async function pollNow() {
    const btn = document.getElementById('btn-poll');
    btn.disabled = true;
    btn.textContent = 'Polling...';
    try {
        const resp = await fetch('/api/poll-now', { method: 'POST' });
        const data = await resp.json();
        showToast(data.message || 'Poll complete');
    } catch (e) {
        showToast('Poll failed', true);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Poll Now';
    }
}

async function generateBriefing() {
    const btn = document.getElementById('btn-briefing');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    try {
        const resp = await fetch('/api/generate-briefing', { method: 'POST' });
        const data = await resp.json();
        if (data.briefing_id) {
            showToast('Briefing generated');
            window.location.href = `/briefings/${data.briefing_id}`;
        } else {
            showToast(data.message || 'No tweets for briefing');
        }
    } catch (e) {
        showToast('Failed to generate briefing', true);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Briefing';
    }
}

async function reclassifyTweet(tweetId, category) {
    if (!category) return;
    try {
        const resp = await fetch(`/api/reclassify/${encodeURIComponent(tweetId)}?category=${category}`, {
            method: 'POST'
        });
        if (resp.ok) showToast('Reclassified');
        else showToast('Failed to reclassify', true);
    } catch (e) {
        showToast('Failed to reclassify', true);
    }
}

function showToast(msg, isError = false) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast' + (isError ? ' error' : '');
    setTimeout(() => { toast.classList.add('hidden'); }, 2500);
}
