import json
import pandas as pd
import nltk
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
import os
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template

nltk.download('punkt')
nltk.download('punkt_tab')

def compute_bleu(reference, candidate):
    """Compute BLEU score between reference and candidate code."""
    reference_tokens = nltk.word_tokenize(reference)
    candidate_tokens = nltk.word_tokenize(candidate)
    smoothie = SmoothingFunction().method4
    return sentence_bleu([reference_tokens], candidate_tokens, smoothing_function=smoothie)

def generate_code(model, tokenizer, prompts, max_new_tokens=512, temperature=1.5, min_p=0.1):
    """
    Generate code outputs for a list of prompts.
    Args:
        model: The fine-tuned LLM model for code generation.
        tokenizer: Tokenizer associated with the model.
        prompts: List of input prompts to generate code for.
        max_new_tokens: Maximum number of tokens to generate (default: 512).
        temperature: Controls randomness in generation - higher values mean more diverse outputs (default: 1.5).
        min_p: Minimum probability threshold for sampling tokens (default: 0.1).

    Returns:
        List of generated code outputs corresponding to each input prompt.
    """

    FastLanguageModel.for_inference(model)

    generated_codes = []
    for prompt in prompts:
        messages = [{"role": "user", "content": prompt}]
        inputs = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt"
        ).to("cuda")

        outputs = model.generate(
            input_ids=inputs,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            temperature=temperature,
            min_p=min_p
        )
        generated_code = tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]
        generated_codes.append(generated_code)
    return generated_codes

def evaluate_model(model, tokenizer, test_dataset_path, train_size, output_prefix="baseline"):
    """Evaluate model performance using BLEU metric."""
    from evaluate import compute_bleu
    from datasets import load_dataset
    from datetime import datetime
    import sys
    import os

    # Add parent directory to path to import retrieve_model_output
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    # Load test dataset
    test_dataset = load_dataset('json', data_files=test_dataset_path, split='train')
    test_df = test_dataset.to_pandas()

    # Extract prompts and references
    def extract_conversations(convo_list):
        try:
            human_msg = convo_list[0]['value']
            assistant_msg = convo_list[1]['value']
            return pd.Series({'prompt': human_msg, 'reference': assistant_msg})
        except (IndexError, KeyError, TypeError) as e:
            print(f"Error extracting conversations: {e}")
            return pd.Series({'prompt': None, 'reference': None})

    test_df[['prompt', 'reference']] = test_df['conversations'].apply(extract_conversations)
    test_df.dropna(subset=['prompt', 'reference'], inplace=True)

    # Generate code
    test_prompts = test_df['prompt'].tolist()
    test_references = test_df['reference'].tolist()
    generated_codes = generate_code(model, tokenizer, test_prompts)

    # Calculate metrics
    bleu_scores = []
    results = []

    # Calculate individual BLEU scores
    for ref, gen in zip(test_references, generated_codes):
        bleu = compute_bleu(ref, gen)
        bleu_scores.append(bleu)

        results.append({
            'reference': ref,
            'generated': gen,
            'bleu': bleu
        })

    # Calculate average scores
    avg_bleu = sum(bleu_scores) / len(bleu_scores)

    avg_metrics = {
        'bleu': avg_bleu
    }

    # Prepare evaluation results
    evaluation_results = {
        'timestamp': datetime.now().isoformat(),
        'average_metrics': avg_metrics,
        'detailed_results': results,
        'training_dataset_size': train_size
    }

    # Create results directory if it doesn't exist
    os.makedirs('./data/results', exist_ok=True)

    # Save evaluation results
    output_file = f'./data/results/evaluation_results_{output_prefix}_{datetime.now().strftime("%Y%m%d")}.json'
    with open(output_file, 'w') as f:
        json.dump(evaluation_results, f, indent=2)

    print(f"\nEvaluation Results ({output_prefix}):")
    print(f"Average BLEU Score: {avg_bleu:.4f}")
    print(f"Detailed results saved to: {output_file}")

    extract_generated_code(output_file, output_prefix)

    return evaluation_results


def extract_generated_code(output_file, output_prefix):
    from retrieve_model_output import process_evaluation_results

    # Extract and save generated code
    generated_code_dir = os.path.join('./data/generated_code', output_prefix)
    success, message, files = process_evaluation_results(output_file, generated_code_dir, file_extension='.txt')
    if success:
        print(f"Generated code samples saved to: {generated_code_dir}")
    else:
        print(f"Warning: Failed to extract code samples: {message}")
