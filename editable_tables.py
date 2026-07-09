"""
editable_tables.py — Eagle 3D Streaming Analytics Hub
========================================================
Google Sheets-style editable tables for any MongoDB collection.

Features:
  - Inline edit any cell -> writes back to MongoDB on save
  - Add new row / delete rows
  - Column filters, sort, search
  - Every change logged to `edit_audit_log` collection
  - Optional per-column validation
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mongo_client import find_all, get_raw_db


def _log_edit(user: str, collection: str, action: str,
               row_key: str, before: Any, after: Any) -> None:
    """Immutable audit log for every table edit."""
    try:
        db = get_raw_db()
        if db is None:
            return
        db["edit_audit_log"].insert_one({
            "timestamp":  datetime.utcnow().isoformat(),
            "user":       user or "unknown",
            "collection": collection,
            "action":     action,   # 'update' / 'insert' / 'delete'
            "row_key":    row_key,
            "before":     before,
            "after":      after,
        })
    except Exception as e:
        print(f"[edit_audit_log] failed: {e}")


def render_editable_table(
    collection: str,
    user_email: str = "",
    *,
    key_field: str = "email_normalized",
    display_columns: Optional[List[str]] = None,
    filter_dict: Optional[Dict[str, Any]] = None,
    max_rows: int = 500,
    hidden_columns: Optional[List[str]] = None,
    allow_add: bool = True,
    allow_delete: bool = True,
    title: str = "",
) -> None:
    """
    Render a MongoDB collection as an editable Google Sheets-style table.

    Args:
        collection:      MongoDB collection name
        user_email:      currently logged-in user (for audit log)
        key_field:       unique identifier field (used for updates/deletes)
        display_columns: which columns to show (None = auto-detect)
        filter_dict:     Mongo filter to limit rows (None = all)
        max_rows:        row limit
        hidden_columns:  columns to hide (defaults to _id, _updated_at, etc.)
        allow_add:       show "add new row" button
        allow_delete:    allow deleting rows
        title:           optional heading
    """
    if title:
        st.markdown(f"### {title}")

    # ── Fetch data ──
    rows = find_all(collection, filters=filter_dict, limit=max_rows,
                     sort=[("_updated_at", -1)])
    if not rows:
        st.info(f"No documents in `{collection}` (with current filter).")
        return

    df = pd.DataFrame(rows)

    # ── Hide system columns ──
    default_hidden = [
        "_id", "_migrated_at", "_updated_at", "_inserted_at",
        "processed_at", "raw_data", "id",
    ]
    hide = set(default_hidden + (hidden_columns or []))
    visible_cols = [c for c in df.columns if c not in hide]
    if display_columns:
        visible_cols = [c for c in display_columns if c in df.columns]
    df_view = df[visible_cols].copy()

    # ── Search / filter ──
    with st.expander("🔍 Filters", expanded=False):
        f1, f2 = st.columns(2)
        with f1:
            search = st.text_input("Search any field",
                                     key=f"search_{collection}")
        with f2:
            if "final_status" in df_view.columns:
                statuses = ["All"] + sorted(
                    df_view["final_status"].fillna("").unique().tolist())
                sel_status = st.selectbox("Status", statuses,
                                           key=f"status_{collection}")
                if sel_status != "All":
                    df_view = df_view[df_view["final_status"] == sel_status]

        if search:
            mask = df_view.astype(str).apply(
                lambda r: r.str.contains(search, case=False, na=False).any(),
                axis=1,
            )
            df_view = df_view[mask]

    st.caption(f"Showing **{len(df_view):,}** of {len(df):,} rows · "
                f"Edit cells inline · Save button below")

    # ── Editor ──
    editor_key = f"editor_{collection}"
    edited_df = st.data_editor(
        df_view,
        num_rows="dynamic" if allow_add else "fixed",
        width='stretch',
        hide_index=True,
        key=editor_key,
        disabled=[key_field] if key_field in df_view.columns else [],
    )

    # ── Save / discard ──
    col_a, col_b, col_c = st.columns([1, 1, 4])
    with col_a:
        save_btn = st.button("💾 Save Changes", type="primary",
                              key=f"save_{collection}",
                              width='stretch')
    with col_b:
        refresh_btn = st.button("🔄 Refresh",
                                  key=f"refresh_{collection}",
                                  width='stretch')

    if refresh_btn:
        st.rerun()

    if save_btn:
        _apply_changes(collection, df_view, edited_df,
                        key_field, user_email, allow_delete)


def _apply_changes(collection: str, before_df: pd.DataFrame,
                    after_df: pd.DataFrame, key_field: str,
                    user_email: str, allow_delete: bool) -> None:
    """Diff before vs after and write changes to MongoDB."""
    db = get_raw_db()
    if db is None:
        st.error("❌ MongoDB offline")
        return

    if key_field not in before_df.columns or key_field not in after_df.columns:
        st.error(f"❌ Key field `{key_field}` missing — cannot save.")
        return

    before_keys = set(before_df[key_field].astype(str).tolist())
    after_keys = set(after_df[key_field].astype(str).tolist())

    n_updated = n_inserted = n_deleted = 0
    errors = []

    # ── UPDATES (rows present in both) ──
    for key in (before_keys & after_keys):
        before_row = before_df[before_df[key_field].astype(str) == key].iloc[0].to_dict()
        after_row  = after_df[after_df[key_field].astype(str)  == key].iloc[0].to_dict()

        changed = {}
        for col in after_df.columns:
            if str(before_row.get(col, "")) != str(after_row.get(col, "")):
                changed[col] = after_row[col]

        if changed:
            changed["_updated_at"] = datetime.utcnow().isoformat()
            changed["_updated_by"] = user_email or "unknown"
            try:
                db[collection].update_one({key_field: key}, {"$set": changed})
                _log_edit(user_email, collection, "update", key,
                           before_row, changed)
                n_updated += 1
            except Exception as e:
                errors.append(f"Update {key}: {e}")

    # ── INSERTS (new rows in after) ──
    for key in (after_keys - before_keys):
        after_row = after_df[after_df[key_field].astype(str) == key].iloc[0].to_dict()
        after_row["_updated_at"] = datetime.utcnow().isoformat()
        after_row["_updated_by"] = user_email or "unknown"
        try:
            db[collection].insert_one(after_row)
            _log_edit(user_email, collection, "insert", key, None, after_row)
            n_inserted += 1
        except Exception as e:
            errors.append(f"Insert {key}: {e}")

    # ── DELETES (rows removed) ──
    if allow_delete:
        for key in (before_keys - after_keys):
            before_row = before_df[before_df[key_field].astype(str) == key].iloc[0].to_dict()
            try:
                db[collection].delete_one({key_field: key})
                _log_edit(user_email, collection, "delete", key,
                           before_row, None)
                n_deleted += 1
            except Exception as e:
                errors.append(f"Delete {key}: {e}")

    # ── Report ──
    total = n_updated + n_inserted + n_deleted
    if total == 0 and not errors:
        st.info("No changes detected.")
    else:
        msgs = []
        if n_updated:  msgs.append(f"✏️ {n_updated} updated")
        if n_inserted: msgs.append(f"➕ {n_inserted} added")
        if n_deleted:  msgs.append(f"🗑️ {n_deleted} deleted")
        st.success(f"✅ Saved: {' · '.join(msgs)}")

    if errors:
        st.error(f"❌ {len(errors)} errors")
        with st.expander("View errors"):
            for e in errors:
                st.code(e)

    if total > 0:
        st.rerun()


def render_audit_log(user_email: str = "", limit: int = 50) -> None:
    """Render recent edit audit log."""
    logs = find_all("edit_audit_log", sort=[("timestamp", -1)], limit=limit)
    if not logs:
        st.info("No edits logged yet.")
        return

    df = pd.DataFrame(logs)
    display = [c for c in ["timestamp", "user", "collection", "action",
                            "row_key"] if c in df.columns]
    st.dataframe(df[display], width='stretch', hide_index=True)

    with st.expander("View change details"):
        for log in logs[:20]:
            st.markdown(f"**{log.get('timestamp','')[:19]}** · "
                         f"{log.get('user','')} · **{log.get('action','')}** "
                         f"on `{log.get('collection','')}` "
                         f"key=`{log.get('row_key','')}`")
            if log.get("before"):
                st.caption("Before:")
                st.json(log["before"], expanded=False)
            if log.get("after"):
                st.caption("After:")
                st.json(log["after"], expanded=False)
            st.markdown("---")
