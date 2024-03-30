# Data

Runs (pickles with data frames and successes / failures) were from our clusters.
The [specs](specs) directory is from [here](https://github.com/buildsi/error-analysis/blob/main/data/spec_files).
What we will try to do is associate metadata from specs with the status (failure or success) and keep the reason
if possible. Here is how to do the extraction, or generation of fax jobspecs and the associated success / failure matrix.

```bash
python extract.py
```

This will generate:

1. The [cluster features](cluster-features.json) (json)
2. The [clusters](clusters) directory and [csv](clusters.csv) with 1000 randomly generated clusters with package dependency subsystems
3. The [prepared](prepared) directory with compatibility matrices, labels, models, and specs
4. [10 fold cross validation](10-fold-scores.json) scores

Finally, to generate our jobpsec yaml:

```bash
python generate-jobspecs.py
```

In all we have:

- 119 unique features (that are package metadata, there can be >1 per subsystem, e.g., `<package>-version` and `<package>-compiler-version`
- 113 unique package subsytems
- 1000 clusters with randomly selected compatibility features
- Over 25K jobspecs (split into groups of 1K so the files aren't too huge)
- 50 models for 50 packages represented in the jobspecs that we want to build
