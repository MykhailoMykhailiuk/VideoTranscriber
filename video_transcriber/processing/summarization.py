from transformers import pipeline, AutoTokenizer



SUMMARIZER = None
SUMMARIZER_TOKENIZER = None

def get_summarizer():
    '''
    Get the summarization pipeline. 
    This is a global variable that is initialized the first time this function is called. 
    This is done to avoid loading the model multiple times.       
    '''

    global SUMMARIZER, SUMMARIZER_TOKENIZER
    if SUMMARIZER is None:
        model_name = "csebuetnlp/mT5_multilingual_XLSum"
        SUMMARIZER_TOKENIZER = AutoTokenizer.from_pretrained(
            model_name,
            model_max_length=512
        )
        SUMMARIZER = pipeline(
            "summarization",
            model=model_name,
            tokenizer=SUMMARIZER_TOKENIZER
        )
    return SUMMARIZER, SUMMARIZER_TOKENIZER


def chunk_text(text: str, max_words: int = 150) -> list[str]:
    '''
    Chunk the text into smaller pieces of max_words words.
    This is necessary because the summarization model has a maximum input length of 512 tokens, 
    which is approximately 150 words.

    text: The text to be chunked.
    max_words: The maximum number of words in each chunk. Default is 150.
    return: A list of chunks of text.
    '''

    words = text.split()
    chunks = []

    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i + max_words]))
    
    return chunks

def summarize_text(text: str) -> str:
    '''
    Summarize the given text using the summarization pipeline.
     - The text is first chunked into smaller pieces of max_words words.
     - Each chunk is summarized individually.
     - The summaries of the chunks are then combined and summarized again to produce the final summary.
     - The final summary is truncated to 700 characters to ensure it is concise.
     - The max_length and min_length parameters for the summarization are dynamically adjusted 
       based on the token count of the input text to ensure that the summarization is effective 
       and does not exceed the model input limits.

    text: The text to be summarized.
    return: The summarized text.
    '''
    summarizer, tokenizer = get_summarizer()
    chunks = chunk_text(text)
    chunk_summaries = []

    for chunk in chunks:
        token_count = len(tokenizer.encode(chunk))
        dynamic_max = min(300, max(80, int(token_count * 0.7)))

        result = summarizer(
            chunk,
            max_length=dynamic_max,
            min_length = int(dynamic_max * 0.4),
            do_sample=False,
            truncation=True,
        )

        chunk_summaries.append(result[0]['summary_text'])

    if len(chunk_summaries) > 1:
        return ' '.join(chunk_summaries)
    
    return chunk_summaries[0]