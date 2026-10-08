from typing_extensions import TypedDict, Annotated


class AudioAnalysisReport(TypedDict):
    main_topic: Annotated[str, ..., "The main subject of the transcription."]
    discussed_points: Annotated[
        str, ..., "List of points discussed in the transcription."
    ]
    decisions_taken: Annotated[
        str, ..., "List of decisions made during the transcription."
    ]
    next_steps: Annotated[str, ..., "Follow-ups."]
    action_points: Annotated[str, ..., "Tasks assigned and responsibilities."]
    named_entities: Annotated[
        str, ..., "List names of people and their corresponding organizations."
    ]
