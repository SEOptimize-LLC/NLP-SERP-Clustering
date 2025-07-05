import streamlit as st
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
# from sentence_transformers import SentenceTransformer  ← not used


# Initialize session state for data and processing status
if 'data' not in st.session_state:
    st.session_state['data'] = None
    st.session_state['processed'] = False

# Upload data file
st.title('Keyword Clustering Based on SERP Overlap')
uploaded_file = st.file_uploader("Upload your keyword CSV file", type=['csv'])

if uploaded_file:
    # Load data into session state
    st.session_state['data'] = pd.read_csv(uploaded_file)
    data = st.session_state['data']

    # Field mapping
    keyword_col = st.selectbox('Select the Keyword column:', data.columns)
    search_volume_col = st.selectbox('Select the Search Volume column:', data.columns)
    position_col = st.selectbox('Select the Position column:', data.columns)
    url_col = st.selectbox('Select the SERP URL column:', data.columns)
    title_col = st.selectbox('Select the Title column:', data.columns)

    # Button to start processing
    if st.button('Run Clustering'):
        # Initialize progress bar and message
        num_unique_keywords = len(data[keyword_col].unique())
        total_keywords = num_unique_keywords
        st.session_state['processed'] = False
        progress_message = st.empty()  # For updating the progress message
        progress_bar = st.progress(0)
        
        clusters = []
        processed_keywords = set()
        duplicates_removed = 0
        keyword_sets_processed = 0

        # Iterate over all unique keyword sets to form clusters
        for i in range(0, len(data), 10):  # Process in batches of 10 rows
            current_keyword_set = data.iloc[i:i + 10]
            current_keyword = current_keyword_set[keyword_col].values[0]

            # Skip if the current keyword is already processed
            if current_keyword in processed_keywords:
                continue

            # Form a new cluster with the current keyword set
            new_cluster = [current_keyword_set]
            current_keyword_urls = current_keyword_set[url_col].values[:10]  # Top 10 URLs

            # Compare to the remaining unprocessed keywords
            for j in range(i + 10, len(data), 10):
                other_keyword_set = data.iloc[j:j + 10]
                other_keyword = other_keyword_set[keyword_col].values[0]

                # Skip if this keyword is already processed
                if other_keyword in processed_keywords:
                    continue

                other_keyword_urls = other_keyword_set[url_col].values[:10]

                # Calculate overlap in top 10 URLs
                overlap_count = len(set(current_keyword_urls) & set(other_keyword_urls))

                if overlap_count > 3:
                    new_cluster.append(other_keyword_set)
                    processed_keywords.add(other_keyword)

            # Post-clustering deduplication: Reduce each keyword set to a single row (since they are identical)
            unique_keywords_in_cluster = {}
            for keyword_set in new_cluster:
                kw = keyword_set[keyword_col].values[0]
                if kw not in unique_keywords_in_cluster or unique_keywords_in_cluster[kw][search_volume_col].sum() < keyword_set[search_volume_col].sum():
                    unique_keywords_in_cluster[kw] = keyword_set.iloc[0:1]  # Keep only the first row of the set

            new_cluster = list(unique_keywords_in_cluster.values())

            # Remove exact matches in top 10 SERP results within the cluster
            keywords_to_remove = set()
            seen_serp_signatures = {}
            for keyword_set in new_cluster:
                serp_signature = tuple(sorted(keyword_set[url_col].values[:10]))  # Top 10 SERP results in any order
                if serp_signature in seen_serp_signatures:
                    if seen_serp_signatures[serp_signature][search_volume_col].sum() < keyword_set[search_volume_col].sum():
                        keywords_to_remove.add(seen_serp_signatures[serp_signature][keyword_col].values[0])
                        seen_serp_signatures[serp_signature] = keyword_set
                    else:
                        keywords_to_remove.add(keyword_set[keyword_col].values[0])
                else:
                    seen_serp_signatures[serp_signature] = keyword_set

            # Remove keywords
            new_cluster = [kw_set for kw_set in new_cluster if kw_set[keyword_col].values[0] not in keywords_to_remove]
            duplicates_removed += len(keywords_to_remove)

            # Set cluster name using TF-IDF
            tfidf_vectorizer = TfidfVectorizer(stop_words='english')
            cluster_texts = [kw_set[keyword_col].values[0] for kw_set in new_cluster]
            tfidf_matrix = tfidf_vectorizer.fit_transform(cluster_texts)
            avg_tfidf = np.mean(tfidf_matrix.toarray(), axis=0)
            top_word_idx = np.argmax(avg_tfidf)
            top_word = tfidf_vectorizer.get_feature_names_out()[top_word_idx]

            cluster_name = max(new_cluster, key=lambda x: top_word in x[keyword_col].values[0])[keyword_col].values[0]

            # Finalize cluster name and add to cluster list
            for keyword_set in new_cluster:
                keyword_set['Cluster Name'] = cluster_name
                processed_keywords.add(keyword_set[keyword_col].values[0])

            clusters.append(new_cluster)

            # Update progress
            keyword_sets_processed += 1
            remaining_keywords = total_keywords - len(processed_keywords)
            progress_percent = min(int((len(processed_keywords) / total_keywords) * 100), 100)
            progress_bar.progress(progress_percent)
            progress_message.text(f"Clustering complete. Keywords left: {remaining_keywords}. Duplicates removed: {duplicates_removed}. Clusters: {len(clusters)}")

        # Convert clusters into a final DataFrame
        final_cluster_df = pd.concat([pd.concat(cluster) for cluster in clusters])

        # Add URL and Title columns for each position
        for pos in range(1, 4):
            final_cluster_df[f'URL {pos}'] = final_cluster_df.apply(lambda row: data[(data[keyword_col] == row[keyword_col]) & (data[position_col] == pos)][url_col].values[0] if len(data[(data[keyword_col] == row[keyword_col]) & (data[position_col] == pos)]) > 0 else None, axis=1)
            final_cluster_df[f'Title {pos}'] = final_cluster_df.apply(lambda row: data[(data[keyword_col] == row[keyword_col]) & (data[position_col] == pos)][title_col].values[0] if len(data[(data[keyword_col] == row[keyword_col]) & (data[position_col] == pos)]) > 0 else None, axis=1)

        # Aggregate and clean up final DataFrame
        final_cluster_df = final_cluster_df.groupby(['Cluster Name', keyword_col], as_index=False).agg({
            search_volume_col: 'sum',
            **{f'URL {pos}': 'first' for pos in range(1, 4)},
            **{f'Title {pos}': 'first' for pos in range(1, 4)}
        })

        # Sort by total volume per cluster
        cluster_volume = final_cluster_df.groupby('Cluster Name')[search_volume_col].sum().reset_index()
        cluster_volume = cluster_volume.rename(columns={search_volume_col: 'Total Volume'})
        final_cluster_df = final_cluster_df.merge(cluster_volume, on='Cluster Name')
        final_cluster_df = final_cluster_df.sort_values(by='Total Volume', ascending=False).drop(columns=['Total Volume'])

        # Store processed data in session state
        st.session_state['data'] = final_cluster_df
        st.session_state['processed'] = True

    # Display the results if processed
    if st.session_state['processed']:
        st.write('Clustered keywords:', st.session_state['data'])
        
        # Download the clustered keywords as a CSV file
        st.download_button(
            label="Download clustered keywords",
            data=st.session_state['data'].to_csv(index=False),
            file_name='clustered_keywords.csv',
            mime='text/csv'
        )
