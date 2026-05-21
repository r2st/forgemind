<script setup>
import { ref, nextTick } from 'vue'
import { Chat } from '../composables/api'

const sessionId = ref(crypto.randomUUID())
const draft = ref('')
const sending = ref(false)
const history = ref([
  { role: 'assistant', content: "Hello. I'm the ChatOps Agent. Ask about incidents, machines, RCA, or shift summaries." },
])
const scroller = ref(null)

const presets = [
  'What incidents fired in the last hour?',
  'Why did CNC-101 degrade?',
  'Predict failures for the next 24h.',
  'Summarize current shift for the executive team.',
  'Show me the riskiest machine and why.',
]

async function send() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  history.value.push({ role: 'user', content: text })
  draft.value = ''
  sending.value = true
  try {
    const resp = await Chat.send(sessionId.value, text)
    history.value.push({
      role: 'assistant',
      content: resp.response || '(empty response)',
      meta: { model: resp.model_used, tokens: resp.tokens, cost: resp.cost_usd, tools: resp.tool_calls },
    })
  } catch (e) {
    history.value.push({ role: 'assistant', content: 'Error: ' + e.message })
  } finally {
    sending.value = false
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  }
}
</script>

<template>
  <div class="h-full flex flex-col gap-4">
    <div>
      <h1 class="text-2xl font-semibold text-slate-100">ChatOps Console</h1>
      <p class="text-sm text-slate-400">Hermes ChatOps Agent · tool-using · routed via TrueFoundry.</p>
    </div>

    <div class="card flex-1 flex flex-col min-h-0">
      <div ref="scroller" class="flex-1 overflow-y-auto space-y-3 pr-2">
        <div v-for="(m, i) in history" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : 'justify-start'">
          <div class="max-w-[80%] rounded-2xl px-4 py-2 text-sm" :class="m.role === 'user' ? 'bg-accent-700 text-ink-900' : 'bg-ink-700 text-slate-100'">
            <div class="whitespace-pre-wrap">{{ m.content }}</div>
            <div v-if="m.meta" class="mt-2 pt-2 border-t border-ink-600/60 text-[10px] text-slate-400 font-mono">
              {{ m.meta.model }} · {{ m.meta.tokens }} tok · ${{ (m.meta.cost || 0).toFixed(5) }} · {{ m.meta.tools?.length || 0 }} tool call(s)
            </div>
          </div>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button v-for="p in presets" :key="p" class="text-xs px-2 py-1 rounded bg-ink-700 hover:bg-ink-600" @click="draft = p">{{ p }}</button>
      </div>

      <div class="mt-3 flex items-end gap-2">
        <textarea
          v-model="draft" rows="2"
          class="flex-1 bg-ink-700 border border-ink-600 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-accent-600"
          placeholder="Ask the ChatOps Agent…"
          @keydown.enter.exact.prevent="send"
        />
        <button class="btn-primary" :disabled="sending" @click="send">{{ sending ? '…' : 'Send' }}</button>
      </div>
    </div>
  </div>
</template>
