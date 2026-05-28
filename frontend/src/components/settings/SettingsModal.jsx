// src/components/settings/SettingsModal.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Settings dialog.
// Opens when the user clicks "Settings" in the sidebar.
// ─────────────────────────────────────────────────────────────────────────────
import { useState }    from 'react'
import { Modal }       from '../ui/Modal'
import { useAuth }     from '../../context/AuthContext'
import { LoadingSpinner } from '../ui/LoadingSpinner'

const TABS = ['Profile']

export function SettingsModal({ open, onClose }) {
  const [activeTab, setActiveTab] = useState('Profile')

  return (
    <Modal open={open} onClose={onClose} title="Settings" width="max-w-[520px]">
      {/* Tab bar */}
      <div className="flex gap-1 mb-5 -mx-5 px-5 border-b border-[#E9DFD1] pb-0">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
              tab === activeTab
                ? 'border-[#B86F50] text-[#B86F50]'
                : 'border-transparent text-[#776B60] hover:text-[#211914]'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'Profile' && <ProfileTab />}
    </Modal>
  )
}

// ── Profile tab ───────────────────────────────────────────────────────────────
function ProfileTab() {
  const { user, logout, authLoading } = useAuth()
  const [name,  setName]  = useState(user?.name  || '')
  const [saved, setSaved] = useState(false)

  async function handleSave(e) {
    e.preventDefault()
    // Call PUT /api/auth/profile in a real app
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-5">
      {/* Avatar */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-full bg-[#776B60] flex items-center justify-center">
          <span className="text-white text-lg font-semibold">
            {(user?.name || user?.email || 'U')[0].toUpperCase()}
          </span>
        </div>
        <div>
          <div className="text-[13px] font-medium text-[#211914]">
            {user?.name || 'User'}
          </div>
          <div className="text-[12px] text-[#776B60]">{user?.email}</div>
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-3">
        <SettingsField label="Display name" value={name} onChange={e => setName(e.target.value)} />

        <div className="flex items-center justify-between pt-1">
          <button
            type="submit"
            className="h-8 px-4 bg-[#B86F50] hover:bg-[#A76145] text-white
                       text-[12px] font-semibold rounded-lg transition-colors"
          >
            {saved ? '✓ Saved' : 'Save changes'}
          </button>
          <button
            type="button"
            onClick={logout}
            disabled={authLoading}
            className="h-8 px-4 text-[12px] text-red-500 hover:bg-red-50
                       rounded-lg transition-colors flex items-center gap-1.5"
          >
            {authLoading && <LoadingSpinner size={12} />}
            Sign out
          </button>
        </div>
      </form>
    </div>
  )
}

// ── Shared sub-components ─────────────────────────────────────────────────────
function SettingsField({ label, type = 'text', value, onChange }) {
  return (
    <div>
      <label className="block text-[12px] font-medium text-[#4A4038] mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={onChange}
        className={settingsInputClass}
      />
    </div>
  )
}

const settingsInputClass =
  'w-full h-9 px-3 bg-[#FCF8F1] border border-[#E2D6C5] rounded-lg ' +
  'text-[13px] text-[#211914] placeholder:text-[#B0A49A] ' +
  'focus:outline-none focus:ring-2 focus:ring-[#B86F50]/20 ' +
  'focus:border-[#B86F50]/60 transition-all'
