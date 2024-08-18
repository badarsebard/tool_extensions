import datetime
from dotenv import load_dotenv
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import time
import uuid
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from flask import Flask, redirect, render_template
from flask import request
from flask_apscheduler import APScheduler
import requests
from sqlalchemy import or_, and_

from todoist import Api
from models import (
    db,
    OauthState,
    RedoistUsers,
    RedoistManifests,
    RedoistNoteIdMap,
    SnoozerUsers,
    SnoozerMap,
)


load_dotenv()
app = Flask(__name__)

# logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
os.makedirs("logs", exist_ok=True)
handler = RotatingFileHandler("logs/app.log", maxBytes=1000000, backupCount=3)
formatter = logging.Formatter("%(asctime)s %(levelname)s - \n%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["SQLALCHEMY_DATABASE_URI"]
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
with app.app_context():
    engine_url = db.engine.url
    db.create_all()


# initialize scheduler
app.config["SCHEDULER_JOBSTORES"] = {"default": SQLAlchemyJobStore(url=engine_url)}
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

###
# ROOT
###


@app.route("/")
def root():
    return render_template("index.html")


###

###
# REDOIST
###


@app.route("/redoist")
def redoist():
    return render_template("redoist.html")


# endpoint for the todoist UI extension
@app.route("/redoist/ui", methods=["GET", "POST"])
def redoist_extension():
    logger.debug(f"{request.method} {request.path}")
    logger.debug(json.dumps(request.json, indent=2, sort_keys=True))
    token = request.headers.get("X-Todoist-Apptoken")
    if not token:
        return {"error": "No token provided."}, 400
    api = Api(token)
    if request.json["extensionType"] == "context-menu":
        if request.json["action"]["actionType"] == "initial":
            # set some vars
            static_url = f"https://{request.host}/static"
            user_id = request.json["context"]["user"]["id"]
            outbound_column = {
                "type": "Column",
                "spacing": "large",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "Outbound",
                    },
                    {
                        "type": "Image",
                        "url": f"{static_url}/outbound.png",
                    },
                ],
            }
            inbound_column = {
                "type": "Column",
                "spacing": "large",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "Inbound",
                    },
                    {
                        "type": "Image",
                        "url": f"{static_url}/inbound.png",
                    },
                ],
            }
            bidirectional_column = {
                "type": "Column",
                "spacing": "large",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "Bidirectional",
                    },
                    {
                        "type": "Image",
                        "url": f"{static_url}/bidirectional.png",
                    },
                ],
            }
            unlink_column = {
                "type": "Column",
                "spacing": "large",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "Unlink",
                    },
                    {
                        "type": "Image",
                        "url": f"{static_url}/unlink.png",
                    },
                ],
            }
            modified_choice_set = {
                "type": "Input.ChoiceSet",
                "spacing": "large",
                "label": "Change sync direction (red icon represents this task)",
                "id": "inputDirection",
                "choices": [],
                # "style": "expanded",
            }

            # look for card id in manifest
            card_id = request.json["action"]["params"]["sourceId"]
            manifest = db.session.scalars(
                db.select(RedoistManifests).where(
                    or_(
                        RedoistManifests.source_id == card_id,
                        RedoistManifests.target_id == card_id,
                    )
                )
            ).all()
            # if found, context menu should provide source and target ids
            if len(manifest) > 0:
                # link exists
                card = {
                    "card": {
                        "type": "AdaptiveCard",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "This task is already linked to another.",
                                "wrap": True,
                            }
                        ],
                    }
                }
                # allow owner to modify direction or unlink
                if manifest[0].user_id == user_id:
                    card["card"]["body"].append(
                        {
                            "type": "ColumnSet",
                            "spacing": "large",
                            "columns": [],
                        }
                    )
                    if len(manifest) > 1:
                        # bidirectional, add outbound, inbound, unlink
                        card["card"]["body"][-1]["columns"].extend(
                            [
                                outbound_column,
                                inbound_column,
                                unlink_column,
                            ]
                        )
                        modified_choice_set["choices"].extend(
                            [
                                {"title": "Outbound", "value": "outbound"},
                                {"title": "Inbound", "value": "inbound"},
                                {"title": "Unlink", "value": "unlink"},
                            ]
                        )
                    else:
                        if manifest[0].source_id == card_id:
                            # outbound, add inbound, bidirectional, unlink
                            card["card"]["body"][-1]["columns"].extend(
                                [
                                    inbound_column,
                                    bidirectional_column,
                                    unlink_column,
                                ]
                            )
                            modified_choice_set["choices"].extend(
                                [
                                    {"title": "Inbound", "value": "inbound"},
                                    {
                                        "title": "Bidirectional",
                                        "value": "bidirectional",
                                    },
                                    {"title": "Unlink", "value": "unlink"},
                                ]
                            )
                        else:
                            # inbound, add outbound, bidirectional, unlink
                            card["card"]["body"][-1]["columns"].extend(
                                [
                                    outbound_column,
                                    bidirectional_column,
                                    unlink_column,
                                ]
                            )
                            modified_choice_set["choices"].extend(
                                [
                                    {"title": "Outbound", "value": "outbound"},
                                    {
                                        "title": "Bidirectional",
                                        "value": "bidirectional",
                                    },
                                    {"title": "Unlink", "value": "unlink"},
                                ]
                            )
                    card["card"]["body"].extend(
                        [
                            {
                                "type": "TextBlock",
                                "spacing": "large",
                                "text": " ",
                            },
                            modified_choice_set,
                        ]
                    )
                    card["card"]["actions"] = [
                        {
                            "type": "Action.Submit",
                            "title": "Submit",
                            "style": "positive",
                            "associatedInputs": "auto",
                        },
                    ]
                else:
                    card["card"]["body"].append(
                        {
                            "type": "TextBlock",
                            "text": "You did not create the link and cannot modify it. Contact the owner to make changes.",
                            "wrap": True,
                        }
                    )
            else:
                # if not found, context menu should provide option to create a new linked task
                projects = api.get_projects()
                prj_map = [{"title": prj.name, "value": prj.id} for prj in projects]
                card = {
                    "card": {
                        "type": "AdaptiveCard",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "Choose the project to create the linked task in.",
                                "wrap": True,
                            },
                            {
                                "type": "Input.ChoiceSet",
                                "label": "Project",
                                "id": "inputProject",
                                "choices": prj_map,
                            },
                            {
                                "type": "TextBlock",
                                "spacing": "large",
                                "text": " ",
                            },
                            {
                                "type": "ColumnSet",
                                "spacing": "large",
                                "columns": [
                                    outbound_column,
                                    inbound_column,
                                    bidirectional_column,
                                ],
                            },
                            {
                                "type": "TextBlock",
                                "spacing": "large",
                                "text": " ",
                            },
                            {
                                "type": "Input.ChoiceSet",
                                "spacing": "large",
                                "label": "Change sync direction (red icon represents this task)",
                                "id": "inputDirection",
                                "choices": [
                                    {"title": "Outbound", "value": "outbound"},
                                    {"title": "Inbound", "value": "inbound"},
                                    {
                                        "title": "Bidirectional",
                                        "value": "bidirectional",
                                    },
                                ],
                                # "style": "expanded",
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.Submit",
                                "title": "Submit",
                                "style": "positive",
                                "associatedInputs": "auto",
                            },
                        ],
                    }
                }
            return card
        if request.json["action"]["actionType"] == "submit":
            # create or modify link
            if "inputProject" in request.json["action"]["inputs"]:
                # create task and link
                # create
                orig_task = api.get_task(request.json["action"]["params"]["sourceId"])
                new_task_kwargs = {
                    "project_id": request.json["action"]["inputs"]["inputProject"],
                    "description": orig_task.description,
                    "order": orig_task.order,
                    "labels": orig_task.labels,
                    "priority": orig_task.priority,
                    "due_datetime": orig_task.due.datetime if orig_task.due else None,
                }
                if orig_task.parent_id:
                    manifest = db.session.scalars(
                        db.select(RedoistManifests).where(
                            RedoistManifests.source_id == orig_task.parent_id
                        )
                    ).one_or_none()
                    if manifest:
                        new_task_kwargs["parent_id"] = manifest.target_id
                new_task = api.add_task(
                    orig_task.content,
                    **new_task_kwargs,
                )
                # link
                # outbound: orig_task -> new_task
                # inbound: orig_task <- new_task
                # bidirectional: orig_task <-> new_task
                source_target_ids = {
                    "outbound": {
                        "source_id": orig_task.id,
                        "target_id": new_task.id,
                    },
                    "inbound": {
                        "source_id": new_task.id,
                        "target_id": orig_task.id,
                    },
                }
                direction = request.json["action"]["inputs"]["inputDirection"]
                user_id = request.json["context"]["user"]["id"]
                if direction == "bidirectional":
                    # create two manifests
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=orig_task.id, target_id=new_task.id
                    )
                    db.session.add(manifest)
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=new_task.id, target_id=orig_task.id
                    )
                    db.session.add(manifest)
                    db.session.commit()
                    # add redoist:bidirectional label to both tasks
                    api.update_task(
                        orig_task.id,
                        labels=[*orig_task.labels, "redoist:bidirectional"],
                    )
                    api.update_task(
                        new_task.id,
                        labels=[*new_task.labels, "redoist:bidirectional"],
                    )
                else:
                    # create one manifest
                    source_id = source_target_ids[direction]["source_id"]
                    target_id = source_target_ids[direction]["target_id"]
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=source_id, target_id=target_id
                    )
                    db.session.add(manifest)
                    db.session.commit()
                    # add redoist:source|destination label to each task
                    api.update_task(
                        source_id,
                        labels=[*orig_task.labels, "redoist:source"],
                    )
                    api.update_task(
                        target_id,
                        labels=[*new_task.labels, "redoist:destination"],
                    )
            else:
                # modify link only
                that_id = None
                this_id = request.json["action"]["params"]["sourceId"]
                user_id = request.json["context"]["user"]["id"]
                manifests = db.session.scalars(
                    db.select(RedoistManifests).where(
                        or_(
                            RedoistManifests.source_id == this_id,
                            RedoistManifests.target_id == this_id,
                        )
                    )
                ).all()
                for manifest in manifests:
                    if manifest.source_id == this_id:
                        that_id = manifest.target_id
                        break
                    if manifest.target_id == this_id:
                        that_id = manifest.source_id
                        break
                this_card = api.get_task(this_id)
                that_card = api.get_task(that_id)
                direction = request.json["action"]["inputs"]["inputDirection"]
                if direction == "unlink":
                    # remove old manifest(s)
                    db.session.execute(
                        db.delete(RedoistManifests).where(
                            or_(
                                RedoistManifests.source_id == this_id,
                                RedoistManifests.target_id == this_id,
                            )
                        )
                    )
                    db.session.commit()
                    # remove redoist labels
                    for label in this_card.labels:
                        if "redoist:" in label:
                            this_card.labels.remove(label)
                    api.update_task(this_id, labels=this_card.labels)
                    for label in that_card.labels:
                        if "redoist:" in label:
                            that_card.labels.remove(label)
                    api.update_task(that_id, labels=that_card.labels)
                elif direction == "outbound":
                    # remove old manifest(s)
                    db.session.execute(
                        db.delete(RedoistManifests).where(
                            or_(
                                RedoistManifests.source_id == this_id,
                                RedoistManifests.target_id == this_id,
                            )
                        )
                    )
                    db.session.commit()
                    # rewrite redoist labels
                    for label in this_card.labels:
                        if "redoist:" in label:
                            this_card.labels.remove(label)
                    this_card.labels.append("redoist:source")
                    api.update_task(this_id, labels=this_card.labels)
                    for label in that_card.labels:
                        if "redoist:" in label:
                            that_card.labels.remove(label)
                    that_card.labels.append("redoist:destination")
                    api.update_task(that_id, labels=that_card.labels)
                    # create new manifest
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=this_id, target_id=that_id
                    )
                    db.session.add(manifest)
                    db.session.commit()
                elif direction == "inbound":
                    # remove old manifest(s)
                    db.session.execute(
                        db.delete(RedoistManifests).where(
                            or_(
                                RedoistManifests.source_id == this_id,
                                RedoistManifests.target_id == this_id,
                            )
                        )
                    )
                    db.session.commit()
                    # rewrite redoist labels
                    for label in this_card.labels:
                        if "redoist:" in label:
                            this_card.labels.remove(label)
                    this_card.labels.append("redoist:destination")
                    api.update_task(this_id, labels=this_card.labels)
                    for label in that_card.labels:
                        if "redoist:" in label:
                            that_card.labels.remove(label)
                    that_card.labels.append("redoist:source")
                    api.update_task(that_id, labels=that_card.labels)
                    # create new manifest
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=that_id, target_id=this_id
                    )
                    db.session.add(manifest)
                    db.session.commit()
                elif direction == "bidirectional":
                    # remove old manifest(s)
                    db.session.execute(
                        db.delete(RedoistManifests).where(
                            or_(
                                RedoistManifests.source_id == this_id,
                                RedoistManifests.target_id == this_id,
                            )
                        )
                    )
                    db.session.commit()
                    # rewrite redoist labels
                    for label in this_card.labels:
                        if "redoist:" in label:
                            this_card.labels.remove(label)
                    this_card.labels.append("redoist:bidirectional")
                    api.update_task(this_id, labels=this_card.labels)
                    for label in that_card.labels:
                        if "redoist:" in label:
                            that_card.labels.remove(label)
                    that_card.labels.append("redoist:bidirectional")
                    api.update_task(that_id, labels=that_card.labels)
                    # create new manifest(s)
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=this_id, target_id=that_id
                    )
                    db.session.add(manifest)
                    manifest = RedoistManifests(
                        user_id=user_id, source_id=that_id, target_id=this_id
                    )
                    db.session.add(manifest)
                    db.session.commit()
            bridge = {"bridges": [{"bridgeActionType": "finished"}]}
            return bridge


# endpoint for the redoist webhook that updates cloned tasks
@app.route("/redoist/update", methods=["POST"])
def redoist_update():
    logger.debug(f"{request.method} {request.path}")
    logger.debug(json.dumps(request.json, indent=2, sort_keys=True))
    user_id = int(request.json["user_id"])
    user = db.session.execute(
        db.select(RedoistUsers).where(RedoistUsers.id == user_id)
    ).scalar_one_or_none()
    if user is None:
        return ""
    api = Api(user.api_key)
    resource_types = '["items", "notes"]'
    sync = api.sync(resource_types, sync_token=user.sync_token)
    user.sync_token = sync["sync_token"]
    db.session.add(user)
    db.session.commit()
    for source_item in sync["items"]:
        source_id = source_item["id"]
        manifest = db.session.scalars(
            db.select(RedoistManifests).where(RedoistManifests.source_id == source_id)
        ).one_or_none()
        if manifest is None:
            continue
        mirror = db.session.scalars(
            db.select(RedoistManifests).where(
                RedoistManifests.source_id == manifest.target_id,
                RedoistManifests.target_id == source_id,
            )
        ).one_or_none()
        is_bidirectional = True if mirror is not None else False
        target_id = manifest.target_id
        if source_item["is_deleted"]:
            # delete target
            api.delete_task(target_id)
            # remove manifests
            db.session.execute(
                db.delete(RedoistManifests).where(
                    or_(
                        RedoistManifests.source_id == source_id,
                        RedoistManifests.target_id == source_id,
                    )
                )
            )
            db.session.commit()
            continue
        if source_item["checked"]:
            # complete target
            api.close_task(target_id)
            # remove manifests
            db.session.execute(
                db.delete(RedoistManifests).where(
                    or_(
                        RedoistManifests.source_id == source_id,
                        RedoistManifests.target_id == source_id,
                    )
                )
            )
            db.session.commit()
            continue

        # check for diff before updating
        orig_target = api.get_task(target_id)
        orig_target_dict = orig_target.to_dict()
        true_source_labels = sorted(
            [label for label in source_item["labels"] if "redoist:" not in label]
        )
        true_target_labels = sorted(
            [label for label in orig_target_dict["labels"] if "redoist:" not in label]
        )
        new_target_kwargs = {}
        for kw in [
            "content",
            "description",
            "priority",
            "parent_id",
        ]:
            if source_item.get(kw) != orig_target_dict.get(kw):
                new_target_kwargs[kw] = source_item.get(kw)
        if true_source_labels != true_target_labels:
            # change in true labels, trigger task update
            complete_target_labels = true_source_labels.copy()
            target_redoist_label = (
                "redoist:bidirectional" if is_bidirectional else "redoist:destination"
            )
            complete_target_labels.append(target_redoist_label)
            new_target_kwargs["labels"] = complete_target_labels
        if source_item.get("due") != orig_target_dict.get("due"):
            # change in due object, check for datetime then use date
            if source_item.get("due"):
                if source_item["due"].get("datetime"):
                    new_target_kwargs["due_datetime"] = source_item["due"]["datetime"]
                else:
                    new_target_kwargs["due_string"] = source_item["due"]["date"]
            else:
                new_target_kwargs["due_string"] = None
        if new_target_kwargs:
            api.update_task(target_id, **new_target_kwargs)

        # does the source item need its redoist label?
        correct_source_redoist_label = (
            "redoist:bidirectional" if is_bidirectional else "redoist:source"
        )
        source_needs_label_update = (
            True if correct_source_redoist_label not in source_item["labels"] else False
        )
        if source_needs_label_update:
            complete_source_labels = true_source_labels.copy()
            complete_source_labels.append(correct_source_redoist_label)
            api.update_task(source_id, labels=complete_source_labels)

    for source_note in sync["notes"]:
        source_item_id = source_note["item_id"]
        manifest = db.session.scalars(
            db.select(RedoistManifests).where(
                RedoistManifests.source_id == source_item_id
            )
        ).one_or_none()
        if manifest is None:
            continue
        mirror = db.session.scalars(
            db.select(RedoistManifests).where(
                RedoistManifests.source_id == manifest.target_id,
                RedoistManifests.target_id == source_item_id,
            )
        ).one_or_none()
        is_bidirectional = True if mirror is not None else False
        note_id_map = db.session.scalars(
            db.select(RedoistNoteIdMap).where(
                RedoistNoteIdMap.source_id == source_note["id"]
            )
        ).one_or_none()

        # note:deleted
        if source_note["is_deleted"]:
            db.session.execute(
                db.delete(RedoistNoteIdMap).where(
                    RedoistNoteIdMap.source_id == source_note["id"]
                )
            )
            if is_bidirectional:
                db.session.execute(
                    db.delete(RedoistNoteIdMap).where(
                        RedoistNoteIdMap.target_id == source_note["id"]
                    )
                )
            db.session.commit()
            if note_id_map:
                api.delete_comment(note_id_map.target_id)
            continue

        # note:added
        if note_id_map is None:
            add_note_kwargs = {
                "task_id": manifest.target_id,
            }
            if source_file := source_note.get("file_attachment"):
                add_note_kwargs["file_attachment"] = {
                    "file_name": source_file["file_name"],
                    "file_size": source_file["file_size"],
                    "file_type": source_file["file_type"],
                    "file_url": source_file["file_url"],
                    "upload_state": source_file["upload_state"],
                }
            add_note = api.add_comment(source_note["content"], **add_note_kwargs)
            note_id_map = RedoistNoteIdMap(
                source_id=source_note["id"],
                target_id=add_note.id,
            )
            db.session.add(note_id_map)
            if is_bidirectional:
                mirror_note_id_map = RedoistNoteIdMap(
                    source_id=add_note.id,
                    target_id=source_note["id"],
                )
                db.session.add(mirror_note_id_map)
            db.session.commit()
            continue

        # note:updated
        if note_id_map:
            target_note_id = note_id_map.target_id
            new_note_kwargs = {}
            orig_target_note = api.get_comment(target_note_id)
            if source_note["content"] != orig_target_note.content:
                new_note_kwargs["content"] = source_note["content"]
            if (
                source_file_attachment := source_note.get("file_attachment")
                != orig_target_note.attachment
            ):
                file_attachment = {
                    "file_name": source_file_attachment["file_name"],
                    "file_size": source_file_attachment["file_size"],
                    "file_type": source_file_attachment["file_type"],
                    "file_url": source_file_attachment["file_url"],
                    "upload_state": source_file_attachment["upload_state"],
                }
                new_note_kwargs["attachment"] = file_attachment
            if new_note_kwargs:
                api.update_comment(target_note_id, **new_note_kwargs)

    return ""


@app.route("/redoist/auth")
def redoist_auth():
    logger.debug(f"{request.method} {request.path}")
    # first clean up expired states
    db.session.execute(
        db.delete(OauthState).where(OauthState.expiration < int(time.time()))
    )
    # begin oauth flow
    client_id = os.environ["REDOIST_CLIENT_ID"]
    state = uuid.uuid4().hex
    oauth_state = OauthState(state=state, expiration=int(time.time()) + 300)
    db.session.add(oauth_state)
    db.session.commit()
    return redirect(
        f"https://todoist.com/oauth/authorize?client_id={client_id}&scope=data:read_write,data:delete&state={state}",
        code=302,
    )


@app.route("/redoist/auth/callback")
def redoist_auth_callback():
    logger.debug(f"{request.method} {request.path}")
    # possible error responses from Todoist (https://developer.todoist.com/guides/#step-1-authorization-request)
    if err := request.args.get("error"):
        # User Rejected Authorization Request; error=access_denied
        if err == "access_denied":
            logger.error("Authorization request denied by user.")
            return "Authorization request denied by user.", 400
        # Invalid Application Status; error=invalid_application_status
        if err == "invalid_application_status":
            logger.error("Invalid application status.")
            return "Invalid application status.", 400

    # successful oauth flow
    code = request.args.get("code")
    client_id = os.environ["REDOIST_CLIENT_ID"]
    client_secret = os.environ["REDOIST_CLIENT_SECRET"]
    state = request.args.get("state")
    oauth_state = db.session.scalars(
        db.select(OauthState).where(OauthState.state == state)
    ).one_or_none()
    if oauth_state is None:
        logger.error("Invalid state.")
        return "Invalid state.", 400
    if int(time.time()) > oauth_state.expiration:
        logger.error("Expired state.")
        db.session.delete(oauth_state)
        db.session.commit()
        return "Expired state.", 400
    t = requests.post(
        "https://todoist.com/oauth/access_token",
        data={"client_id": client_id, "client_secret": client_secret, "code": code},
    )
    logger.debug(f"Token exchange resulted in status code: {t.status_code}")
    if t.ok:
        # {
        #   "access_token": "0123456789abcdef0123456789abcdef01234567",
        #   "token_type": "Bearer"
        # }
        token = t.json()
        api_key = token.get("access_token")
        api = Api(api_key)
        # get user info
        user_info = api.sync(["user"])
        user_id = user_info.get("user").get("id") if user_info.get("user") else None
        if not user_id:
            return "Failed to get user info.", 400

        user = db.session.execute(
            db.select(RedoistUsers).where(RedoistUsers.id == user_id)
        ).scalar_one_or_none()

        # save user to db
        if user is None:
            user = RedoistUsers(id=user_id, api_key=api_key)
        db.session.add(user)
        db.session.delete(oauth_state)
        db.session.commit()
        return render_template("auth_success.html")
    else:
        return "Token exchange failed.", 400


###
# SNOOZER
###


@app.route("/snoozer")
def snoozer():
    return render_template("snoozer.html")


@app.route("/snoozer/ui", methods=["GET", "POST"])
def snoozer_ui():
    logger.debug(f"{request.headers}")
    logger.debug(json.dumps(request.json, indent=2, sort_keys=True))
    user_timezone = request.json["context"]["user"]["timezone"]
    user_tz = ZoneInfo(user_timezone)
    now = datetime.datetime.now(tz=user_tz)
    today = f"{now.year}-{now.month:02d}-{now.day:02d}"
    current_time = f"{now.hour:02d}:{now.minute:02d}"
    if request.json["action"]["actionType"] == "initial":
        card = {
            "card": {
                "body": [
                    {
                        "type": "ActionSet",
                        "id": "dayChoice",
                        "orientation": "vertical",
                        "actions": [
                            {
                                "id": "Action.Today",
                                "type": "Action.Submit",
                                "title": "Today",
                                "style": "positive",
                                "data": "today",
                            },
                            {
                                "id": "Action.Tomorrow",
                                "type": "Action.Submit",
                                "title": "Tomorrow",
                                "style": "positive",
                                "data": "tomorrow",
                            },
                            {
                                "id": "Action.Weekend",
                                "type": "Action.Submit",
                                "title": "Next Weekend",
                                "style": "positive",
                                "data": "weekend",
                            },
                            {
                                "id": "Action.Week",
                                "type": "Action.Submit",
                                "title": "Next Week",
                                "style": "positive",
                                "data": "week",
                            },
                        ],
                    },
                    {
                        "id": "Input.Date",
                        "separator": True,
                        "spacing": "large",
                        "type": "Input.Date",
                        "value": today,
                    },
                    {
                        "id": "Input.Time",
                        "spacing": "large",
                        "type": "Input.Time",
                        "value": current_time,
                    },
                ],
                "actions": [
                    {
                        "id": "Action.Inputs",
                        "type": "Action.Submit",
                        "title": "Submit",
                        "style": "positive",
                    },
                ],
            }
        }
        logger.debug(json.dumps(card, indent=2, sort_keys=True))
        return card

    if request.json["action"]["actionType"] == "submit":
        user_id = request.json["context"]["user"]["id"]
        user = db.session.execute(
            db.select(SnoozerUsers).where(SnoozerUsers.id == user_id)
        ).scalar_one_or_none()
        if user is None:
            return {"error": "No user found."}, 400
        api_key = user.api_key
        api = Api(api_key)
        if request.json["action"]["actionId"] == "Action.Inputs":
            input_date = request.json["action"]["inputs"].get("Input.Date")
            if input_date is None:
                input_date = today
            input_time = request.json["action"]["inputs"].get("Input.Time")
            if input_time is None:
                input_time = current_time
            expiration = datetime.datetime.strptime(
                f"{input_date} {input_time}", "%Y-%m-%d %H:%M"
            )
        else:
            data = request.json["action"]["data"]
            if data == "today":
                expiration = now + datetime.timedelta(hours=4)
            elif data == "tomorrow":
                expiration = now + datetime.timedelta(days=1)
            elif data == "weekend":
                expiration = now + datetime.timedelta((12 - now.weekday()) % 7)
            elif data == "week":
                expiration = now + datetime.timedelta(days=7)
            else:
                expiration = now
        # move task and create job
        task_id = request.json["action"]["params"]["sourceId"]
        task = api.get_task(task_id)
        source_project_id = task.project_id
        source_section_id = task.section_id
        snooze_map = db.session.execute(
            db.select(SnoozerMap).where(
                and_(
                    SnoozerMap.user_id == user_id,
                    SnoozerMap.source_project_id == source_project_id,
                )
            )
        ).scalar_one_or_none()
        if snooze_map is None:
            return {"error": "Snoozer not configured for this project."}, 400
        target_section_id = snooze_map.target_section_id
        api.move_task(task_id=task_id, section_id=target_section_id)
        job_id = uuid.uuid4().hex
        kwargs = {"task_id": task_id}
        if target_section_id == "0":
            kwargs["project_id"] = source_project_id
        else:
            kwargs["section_id"] = source_section_id
        logger.debug(f"Job ID: {job_id}")
        logger.debug(f"Job Args: {kwargs}")
        scheduler.add_job(
            job_id,
            api.move_task,
            kwargs=kwargs,
            trigger="date",
            run_date=expiration,
        )
        return {"bridges": [{"bridgeActionType": "finished"}]}

    return {"error": "Invalid action type."}, 400


@app.route("/snoozer/settings", methods=["GET", "POST"])
def snoozer_settings():
    logger.debug(f"{request.method} {request.path}")
    logger.debug(json.dumps(request.json, indent=2, sort_keys=True))
    user_id = request.json["context"]["user"]["id"]
    user = db.session.execute(
        db.select(SnoozerUsers).where(SnoozerUsers.id == user_id)
    ).scalar_one_or_none()
    if user is None:
        return {"error": "No user found."}, 400
    api_key = user.api_key
    if request.json["action"]["actionType"] == "initial":
        card = get_snoozer_settings_card(user_id, api_key)
        return card
    if request.json["action"]["actionType"] == "submit":
        if request.json["action"]["actionId"] == "Action.Changed.Input.Project":
            chosen_project = request.json["action"]["inputs"]["Input.Project"]
            card = get_snoozer_settings_card(
                user_id, api_key, chosen_project=chosen_project
            )
            return card
        if request.json["action"]["actionId"] == "Action.Submit.Final":
            project_id = request.json["action"]["inputs"]["Input.Project"]
            section_id = request.json["action"]["inputs"]["Input.Section"]
            snooze_map = db.session.execute(
                db.select(SnoozerMap).where(
                    and_(
                        SnoozerMap.user_id == user_id,
                        SnoozerMap.source_project_id == project_id,
                    )
                )
            ).scalar_one_or_none()
            if snooze_map is not None:
                snooze_map.target_section_id = section_id
            else:
                snooze_map = SnoozerMap(
                    user_id=user_id,
                    source_project_id=project_id,
                    target_section_id=section_id,
                )
                db.session.add(snooze_map)
            db.session.commit()
            card = get_snoozer_settings_card(user_id, api_key)
            return card


def get_snoozer_settings_card(user_id, api_key, chosen_project=None):
    api = Api(api_key)
    projects = api.get_projects()
    project_map = {}
    section_map = {}
    for project in projects:
        project_map[project.id] = project.name
        project_map[project.name] = project.id
        section_map[project.id] = {
            "0": "(no section)",
            "(no section)": "0",
        }
    sections = api.get_sections()
    for section in sections:
        section_map[section.project_id][section.id] = section.name
        section_map[section.project_id][section.name] = section.id
    card = {
        "card": {
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Current Snooze Sections",
                    "size": "extraLarge",
                }
            ],
        }
    }
    snooze_maps = db.session.execute(
        db.select(SnoozerMap).where(SnoozerMap.user_id == user_id)
    ).scalars()
    for snooze_map in snooze_maps:
        sm_el = {
            "type": "TextBlock",
            "text": f"{project_map[snooze_map.source_project_id]}: {section_map[snooze_map.source_project_id][snooze_map.target_section_id]}",
        }
        card["card"]["body"].append(sm_el)
    if len(card["card"]["body"]) == 0:
        card["card"]["body"].append(
            {
                "type": "TextBlock",
                "text": "No Snooze Sections configured.",
            }
        )
    card["card"]["body"].append(
        {
            "separator": True,
            "spacing": "large",
            "type": "TextBlock",
            "size": "extraLarge",
            "text": "Add a new Snooze Section",
        }
    )
    project_choices = [{"title": "", "value": "0", "disabled": True}]
    project_choices.extend(
        [{"title": project.name, "value": project.id} for project in projects]
    )
    project_input = {
        "type": "Input.ChoiceSet",
        "id": "Input.Project",
        "label": "Choose a project",
        "choices": project_choices,
        "value": "0",
        "selectAction": {
            "type": "Action.Submit",
            "id": "Action.Changed.Input.Project",
            "data": "submit",
        },
    }
    if chosen_project is not None:
        project_input["value"] = chosen_project
    card["card"]["body"].append(project_input)
    if chosen_project is not None:
        project_id = chosen_project
        section_choices = [{"title": "(no section)", "value": None}]
        section_choices.extend(
            [
                {"title": section.name, "value": section.id}
                for section in sections
                if section.project_id == project_id
            ]
        )
        card["card"]["actions"] = [
            {
                "id": "Action.Submit.Final",
                "type": "Action.Submit",
                "title": "Submit",
                "style": "positive",
            }
        ]
    else:
        section_choices = [
            {"title": "Choose a project first", "value": "0", "disabled": True}
        ]
    section_input = {
        "type": "Input.ChoiceSet",
        "id": "Input.Section",
        "label": "Choose a section",
        "choices": section_choices,
        "value": "0",
    }
    card["card"]["body"].append(section_input)
    return card


@app.route("/snoozer/auth")
def snoozer_auth():
    # first clean up expired states
    db.session.execute(
        db.delete(OauthState).where(OauthState.expiration < int(time.time()))
    )
    # begin oauth flow
    client_id = os.environ["SNOOZER_CLIENT_ID"]
    state = uuid.uuid4().hex
    oauth_state = OauthState(state=state, expiration=int(time.time()) + 300)
    db.session.add(oauth_state)
    db.session.commit()
    return redirect(
        f"https://todoist.com/oauth/authorize?client_id={client_id}&scope=data:read_write&state={state}",
        code=302,
    )


@app.route("/snoozer/auth/callback")
def snoozer_auth_callback():
    # possible error responses from Todoist (https://developer.todoist.com/guides/#step-1-authorization-request)
    if err := request.args.get("error"):
        # User Rejected Authorization Request; error=access_denied
        if err == "access_denied":
            return "Authorization request denied by user."
        # Invalid Application Status; error=invalid_application_status
        if err == "invalid_application_status":
            return "Invalid application status."

    # successful oauth flow
    code = request.args.get("code")
    client_id = os.environ["SNOOZER_CLIENT_ID"]
    client_secret = os.environ["SNOOZER_CLIENT_SECRET"]
    state = request.args.get("state")
    oauth_state = db.session.scalars(
        db.select(OauthState).where(OauthState.state == state)
    ).one_or_none()
    if oauth_state is None:
        return "Invalid state."
    if int(time.time()) > oauth_state.expiration:
        db.session.delete(oauth_state)
        db.session.commit()
        return "Expired state."
    t = requests.post(
        "https://todoist.com/oauth/access_token",
        data={"client_id": client_id, "client_secret": client_secret, "code": code},
    )
    # {
    #   "access_token": "0123456789abcdef0123456789abcdef01234567",
    #   "token_type": "Bearer"
    # }
    token = t.json()
    api_key = token.get("access_token")
    api = Api(api_key)
    # get user info
    user_info = api.sync(["user"])
    user_id = user_info.get("user").get("id") if user_info.get("user") else None
    if not user_id:
        return "Failed to get user info."

    user = db.session.execute(
        db.select(SnoozerUsers).where(SnoozerUsers.id == user_id)
    ).scalar_one_or_none()

    # save user to db
    if user is None:
        user = SnoozerUsers(id=user_id, api_key=api_key)
    db.session.add(user)
    db.session.delete(oauth_state)
    db.session.commit()
    return render_template("auth_success.html")


###
# SLACK-TO-DO
###


@app.route("/slack-to-do")
def slack_to_do():
    return render_template("slack-to-do.html")


@app.route("/slack-to-do/events", methods=["POST"])
def slack_events():
    if challenge := request.json.get("challenge"):
        return challenge, 200, {"Content-Type": "text/plain"}


if __name__ == "__main__":
    app.run()
