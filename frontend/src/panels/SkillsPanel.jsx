import { useEffect, useState } from 'react';
import { Panel } from '../components/Panel';
import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';

const CUSTOM_ID = 'custom';

/**
 * Picks how the camera talks.
 *
 * The persona text itself never reaches the browser — only a name, a one-line
 * blurb and an icon — so the prompt stays on the server. Choosing is optimistic
 * in feel but authoritative in fact: the backend's reply is what updates the
 * list, and a broadcast keeps other open tabs in step.
 */
export function SkillsPanel({ skills, selectSkill, mode }) {
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState('');

  const activeId = skills?.active_id ?? null;
  const items = skills?.skills ?? [];
  const maxChars = skills?.max_persona_chars ?? 2000;

  // Keep the editor in step when the active persona changes elsewhere.
  useEffect(() => {
    setDraft(skills?.custom_persona ?? '');
  }, [skills?.custom_persona]);

  if (mode === 'demo' || !skills) {
    return (
      <Panel
        title={
          <>
            <Icon name="sparkle" size={17} />
            Skills
          </>
        }
        className="span-2"
      >
        <EmptyState
          icon="sparkle"
          title="Skills need the app running"
          hint="Start the app and reload to choose how the camera describes what it sees — as a news reporter, a nature documentary, an inspector and more."
        />
      </Panel>
    );
  }

  async function choose(id, persona) {
    setBusyId(id);
    setError(null);
    try {
      await selectSkill(id, persona);
    } catch (failure) {
      setError(failure.message ?? 'Could not change the skill.');
    } finally {
      setBusyId(null);
    }
  }

  const customActive = activeId === CUSTOM_ID;
  const dirty = draft.trim() !== (skills?.custom_persona ?? '').trim();

  return (
    <Panel
      title={
        <>
          <Icon name="sparkle" size={17} />
          Skills
        </>
      }
      subtitle="How the camera describes what it sees"
      className="span-2"
    >
      <ul className="skill-grid">
        {items.map((skill) => {
          const isActive = skill.id === activeId;
          return (
            <li key={skill.id}>
              <button
                type="button"
                className={`skill-card ${isActive ? 'is-active' : ''}`.trim()}
                aria-pressed={isActive}
                disabled={busyId !== null}
                onClick={() =>
                  choose(skill.id, skill.id === CUSTOM_ID ? draft : undefined)
                }
              >
                <span className="skill-icon">
                  <Icon name={skill.icon} size={16} />
                </span>
                <span className="skill-text">
                  <span className="skill-name">{skill.name}</span>
                  <span className="skill-blurb">{skill.blurb}</span>
                </span>
                {isActive ? (
                  <span className="skill-check" aria-hidden="true">
                    <Icon name="check" size={14} />
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>

      {customActive ? (
        <div className="skill-editor">
          <label className="skill-editor-label" htmlFor="custom-persona">
            Describe who the camera should be
          </label>
          <textarea
            id="custom-persona"
            className="skill-textarea"
            rows={3}
            maxLength={maxChars}
            value={draft}
            placeholder={skills?.custom_placeholder ?? ''}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="skill-editor-foot">
            <span className="muted small">
              {draft.length} / {maxChars}
            </span>
            <Button
              variant="primary"
              disabled={!dirty || busyId !== null}
              onClick={() => choose(CUSTOM_ID, draft)}
            >
              {dirty ? 'Save and use' : 'Saved'}
            </Button>
          </div>
        </div>
      ) : null}

      {error ? <p className="small is-bad">{error}</p> : null}

      <p className="muted small">
        Changing the skill starts the running commentary fresh, so it will not
        refer back to anything the previous one said.
      </p>
    </Panel>
  );
}
